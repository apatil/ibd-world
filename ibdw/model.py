# Author: Anand Patil
# Date: 6 Feb 2009
# License: Creative Commons BY-NC-SA
####################################


import numpy as np
import pymc as pm
import gc
from map_utils import *
from generic_mbg import *
import generic_mbg
__all__ = ['make_model']
from ibdw import cut_matern

# The parameterization of the cut between western and eastern hemispheres.
#
# t = np.linspace(0,1,501)
# 
# def latfun(t):
#     if t<.5:
#         return (t*4-1)*np.pi
#     else:
#         return ((1-t)*4-1)*np.pi
#         
# def lonfun(t):
#     if t<.25:
#         return -28*np.pi/180.
#     elif t < .5:
#         return -28*np.pi/180. + (t-.25)*3.5
#     else:
#         return -169*np.pi/180.
#     
# lat = np.array([latfun(tau)*180./np.pi for tau in t])    
# lon = np.array([lonfun(tau)*180./np.pi for tau in t])


def ibd_covariance_submodel(mesh):
    """
    A small function that creates the mean and covariance object
    of the random field.
    """
    
    # The fraction of the partial sill going to 'short' variation.
    amp_short_frac = pm.Uniform('amp_short_frac',0,1)
    
    # The partial sill.
    amp = pm.Exponential('amp', .1, value=1.)
    
    # The range parameters. Units are RADIANS. 
    # 1 radian = the radius of the earth, about 6378.1 km
    # scale = pm.Exponential('scale', 1./.08, value=.08)
    
    scale_shift = pm.Exponential('scale_shift', .1, value=.08)
    scale = pm.Lambda('scale',lambda s=scale_shift: s+.01)
    scale_in_km = scale*6378.1
    
    # This parameter controls the degree of differentiability of the field.
    diff_degree = pm.Uniform('diff_degree', .01, 1.5)
    
    # The nugget variance.
    V = pm.Exponential('V', .1, value=1.)
    
    @pm.deterministic(trace=True)
    def M():
        return pm.gp.Mean(pm.gp.zero_fn)
    
    # Create the covariance & its evaluation at the data locations.
    @pm.deterministic(trace=True)
    def C(amp=amp, scale=scale, diff_degree=diff_degree):
        """A covariance function created from the current parameter values."""
        return pm.gp.FullRankCovariance(cut_matern, amp=amp, scale=scale, diff_degree=diff_degree)
        
    sp_sub = pm.gp.GPSubmodel('sp_sub',M,C,mesh)
    
    sp_sub.f_eval.value = sp_sub.f_eval.value - sp_sub.f_eval.value.mean()    
    
    return locals()
    
    
def make_model(lon,lat,covariate_values,pos,neg,cpus=1):
    """
    This function is required by the generic MBG code.
    """
    
    for col in lon,lat,pos,neg:
        if np.any(np.isnan(col)):
            raise ValueError, 'NaN found in the following rows of the datafile: \n%s'%(np.where(np.isnan(col))[0])
    
    if np.any(pos+neg==0):
        where_zero = np.where(pos+neg==0)[0]
        raise ValueError, 'Pos+neg = 0 in the rows (starting from zero):\n %s'%where_zero
    
    # How many nuggeted field points to handle with each step method
    grainsize = 10
        
    # Non-unique data locations
    data_mesh = combine_spatial_inputs(lon, lat)
    
    s_hat = (pos+1.)/(pos+neg+2.)
    
    # Uniquify the data locations.
    locs = [(lon[0], lat[0])]
    fi = [0]
    ui = [0]
    for i in xrange(1,len(lon)):

        # If repeat location, add observation
        loc = (lon[i], lat[i])
        if loc in locs:
            fi.append(locs.index(loc))

        # Otherwise, new obs
        else:
            locs.append(loc)
            fi.append(max(fi)+1)
            ui.append(i)
    fi = np.array(fi)
    ti = [np.where(fi == i)[0] for i in xrange(max(fi)+1)]
    ui = np.asarray(ui)

    lon = np.array(locs)[:,0]
    lat = np.array(locs)[:,1]

    # Unique data locations
    logp_mesh = combine_spatial_inputs(lon,lat)
        
    # Space-time component
    spatial_vars = ibd_covariance_submodel(logp_mesh)    
    sp_sub = spatial_vars['sp_sub']

    # Loop over data clusters
    eps_p_f_d = []
    s_d = []
    data_d = []

    for i in xrange(len(pos)/grainsize+1):
        sl = slice(i*grainsize,(i+1)*grainsize,None)
        # Nuggeted field in this cluster
        eps_p_f_d.append(pm.Normal('eps_p_f_%i'%i, sp_sub.f_eval[fi[sl]], 1./spatial_vars['V'], value=pm.logit(s_hat[sl]),trace=False))

        # The allele frequency
        s_d.append(pm.Lambda('s_%i'%i,lambda lt=eps_p_f_d[-1]: invlogit(lt),trace=False))

        # The observed allele frequencies
        data_d.append(pm.Binomial('data_%i'%i, pos[sl]+neg[sl], s_d[-1], value=pos[sl], observed=True))
    
    # The field plus the nugget
    @pm.deterministic
    def eps_p_f(eps_p_fd = eps_p_f_d):
        """Concatenated version of eps_p_f, for postprocessing & Gibbs sampling purposes"""
        return np.concatenate(eps_p_fd)
    
    init_OK = True        

    out = locals()
    out.pop('spatial_vars')
    out.update(spatial_vars)

    return out
