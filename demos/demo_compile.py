'''
Created on Dec 15, 2011

@author: sean
'''


import opencl as cl
import clyther as cly

import clyther.runtime as clrt

#Always have to create a context.
ctx = cl.Context()

@cly.global_work_size(lambda a: [a.size])
@cly.kernel
def generate_sin(a):
    
    gid = clrt.get_global_id(0)
    n = clrt.get_global_size(0)
    
    r = cl.cl_float(gid) / cl.cl_float(n)
    
    # sin wave with 8 peaks
    y = r * cl.cl_float(16.0 * 3.1415)
    
    # x is a range from -1 to 1
    a[gid].x = r * 2.0 - 1.0
    
    # y is sin wave
    a[gid].y = clrt.native_sin(y)


#===============================================================================
# Compile to openCL code 
#===============================================================================

print generate_sin.compile(ctx, a=cl.global_memory(cl.cl_float2), source_only=True) 

