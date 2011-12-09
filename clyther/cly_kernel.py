'''
Created on Dec 4, 2011

@author: sean
'''

from meta.decompiler import decompile_func
from clyther.rttt import replace_types

from clyther.clast.openCL_sourcegen import opencl_source
from clyther.clast.visitors.typify import Typify
from clyther.clast.mutators.type_cast import call_type2type_cast
from clyther.clast.mutators.rm_const_params import remove_const_params
from clyther.clast.mutators.keywords import move_keywords_to_args
from clyther.clast.mutators.placeholder_replace import resolve_functions

from clyther.clast.visitors.returns import return_nodes
from clyther.clast import cast
import opencl as cl
from meta.asttools.visitors.print_visitor import print_ast
from opencl import global_memory
from clyther.clast.mutators.unpacker import unpack_mem_args
from clyther.clast.mutators.for_loops import format_for_loops
from clyther.queue_record import QueueRecord, EventRecord

class ClytherKernel(object):
    pass

class CLComileError(Exception):
    pass

def typeof(obj):
    if isinstance(obj, cl.MemoryObject):
        return global_memory(obj.format, obj.shape)
    else:
        return type(obj)
    
class kernel(object):
    
    def __init__(self, func):
        self.func = func
        self.__doc__ = self.func.__doc__ 
        self.global_work_size = None
        self._cache = {}
    
    def __call__(self, queue, *args, **kwargs):
        
        cache = self._cache.setdefault(queue.context, {})
        
        argnames = self.func.func_code.co_varnames[:self.func.func_code.co_argcount]
        defaults = self.func.func_defaults
        arglist = cl.kernel.parse_args(self.func.__name__, args, kwargs, argnames, defaults)
        
        kwarg_types = {argnames[i]:typeof(arglist[i]) for i in range(len(argnames))}
        
        
        cl_kernel = self.compile(queue.context, **kwarg_types)
        
        cache[tuple(sorted(kwarg_types.viewitems(), key=lambda item:item[0]))] = cl_kernel 
        
        kernel_args = {}
        for name, arg  in zip(argnames, arglist):
            kernel_args[name] = arg
            if isinstance(arg, cl.DeviceMemoryView):
                kernel_args['cly_%s_info' % name] = arg.array_info
        
        event = cl_kernel(queue, global_work_size=kwargs.get('global_work_size'),
                                 global_work_offset=kwargs.get('global_work_offset'),
                                 local_work_size=kwargs.get('local_work_size'),
                                 **kernel_args)
        
        #FIXME: I don't like that this breaks encapsulation
        if isinstance(event, EventRecord):
            event.set_kernel_args(kernel_args)
            
        return event
    
    def compile(self, ctx, source_only=False, **kwargs):
        args, defaults, source, kernel_name = create_kernel_source(self.func, kwargs)
        
        if source_only:
            return source
        
        program = cl.Program(ctx, source)
        
        try:
            program.build()
        except cl.OpenCLException:
            log_lines = []
            for device, log in program.logs.items():
                log_lines.append(repr(device))
                log_lines.append(log)
                
            raise CLComileError('\n'.join(log_lines))
        
        for device, log in program.logs.items():
            if log: print log
            
        kernel = program.kernel(kernel_name)
        
        kernel.global_work_size = self.global_work_size
        kernel.argtypes = [arg[1] for arg in args]
        kernel.argnames = [arg[0] for arg in args]
        kernel.__defaults__ = defaults
        
        return kernel

def global_work_size(arg):
    def decorator(func):
        func.global_work_size = arg
        return func
    return decorator
def local_work_size(arg):
    def decorator(func):
        func.local_work_size = arg
        return func
    return decorator

def make_kernel(cfunc_def):
    returns = return_nodes(cfunc_def.body)
    for return_node in returns:
        return_node.value = None
    
    cfunc_def.decorator_list.insert(0, cast.clkernel())
    cfunc_def.return_type = None
    
    
def typify_function(argtypes, globls, node):
    typify = Typify(argtypes, globls)
    func_ast = typify.make_cfunction(node)
    make_kernel(func_ast)
    return typify.make_module(func_ast), func_ast


def create_kernel_source(function, argtypes):
    
    func_ast = decompile_func(function)
    
#    print_ast(func_ast)

    globls = function.func_globals
    
    mod_ast, func_ast = typify_function(argtypes, globls, func_ast)
    
    unpack_mem_args(mod_ast, argtypes)
    # convert type calls to casts 
    # eg int(i) -> ((int) (i))
    call_type2type_cast(mod_ast)
    
    format_for_loops(mod_ast)
    
    # Remove arguments to functions that are constant
    # eg. functions modules. etc
    remove_const_params(mod_ast)
    
    #C/opencl do not accept keword arguments. 
    #This moves them to positional arguments 
    move_keywords_to_args(mod_ast)
    
    #typify created function placeholders. resolve them here 
    resolve_functions(mod_ast)
    
    defaults = function.func_defaults
    
    args = [(arg.id, arg.ctype) for arg in func_ast.args.args]
    
    #replace python type objects with strings 
    replace_types(mod_ast)
    
    #generate source
    return args, defaults, opencl_source(mod_ast), func_ast.name
    
