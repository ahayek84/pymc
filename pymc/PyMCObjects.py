__docformat__='reStructuredText'
__author__ = 'Anand Patil, anand.prabhakar.patil@gmail.com'
__all__ = ['extend_children', 'extend_parents', 'ParentDict', 'Stochastic', 'Deterministic', 'Potential']


from copy import copy
from numpy import array, ndarray, reshape, Inf, asarray, dot, sum, float, isnan, size
from Node import Node, ZeroProbability, Variable, PotentialBase, StochasticBase, DeterministicBase
from Container import DictContainer, ContainerBase, file_items
import pdb

d_neg_inf = float(-1.79E308)

# from PyrexLazyFunction import LazyFunction
from LazyFunction import LazyFunction

def extend_children(children):
    """
    extend_children(children)
    
    Returns a set containing
    nearest conditionally stochastic (Stochastic, not Deterministic) descendants.
    """
    new_children = copy(children)
    need_recursion = False
    dtrm_children = set()

    for child in children:
        if isinstance(child,Deterministic):
            new_children |= child.children
            dtrm_children.add(child)
            need_recursion = True

    new_children -= dtrm_children

    if need_recursion:
        new_children = extend_children(new_children)

    return new_children
    
def extend_parents(parents):
    """
    extend_parents(parents)
    
    Returns a set containing
    nearest conditionally stochastic (Stochastic, not Deterministic) ancestors.
    """
    new_parents = set()
    
    for parent in parents:

        new_parents.add(parent)

        if isinstance(parent, DeterministicBase):
            new_parents.remove(parent)
            new_parents |= parent.extended_parents
                
        elif isinstance(parent, ContainerBase):
            for contained_parent in parent.stochastics:
                new_parents.add(contained_parent)
            for contained_parent in parent.deterministics:
                new_parents |= contained_parent.extended_parents
                    

    return new_parents


class ParentDict(DictContainer):
    """
    A special subclass of DictContainer which makes it safe to change 
    varibales' parents. When __setitem__ is called, a ParentDict instance
    removes its owner from the old parent's children set (if appropriate)
    and adds its owner to the new parent's children set. It then asks
    its owner to generate a new LazyFunction instance using its new
    parents.
    
    Also manages the extended_parents attribute of owner.

    NB: StepMethod and Model are expecting variables'
    children to be static. If you want to change indedependence structure
    over the course of an MCMC loop, please do so with indicator variables.
    
    :SeeAlso: DictContainer
    """
    def __init__(self, regular_dict, owner):
        DictContainer.__init__(self, dict(regular_dict))
        self.owner = owner
        self.owner.extended_parents = extend_parents(self.variables)
        if isinstance(self.owner, StochasticBase) or isinstance(self.owner, PotentialBase):
            self.has_logp = True
        else:
            self.has_logp = False

    def detach_parents(self):
        for parent in self.itervalues():
            if isinstance(parent, Variable):
                parent.children.discard(self.owner)
            elif isinstance(parent, ContainerBase):
                for variable in parent.variables:
                    variable.chidren.discard(self.owner)
                    
        if self.has_logp:
            self.detach_extended_parents()
    
    
    def detach_extended_parents(self):                
        for e_parent in self.owner.extended_parents:
            if isinstance(e_parent, StochasticBase):
                e_parent.extended_children.discard(self.owner)
            
                    
    def attach_parents(self):
        for parent in self.itervalues():
            if isinstance(parent, Variable):
                parent.children.add(self.owner)
            elif isinstance(parent, ContainerBase):
                for variable in parent.variables:
                    variable.children.add(self.owner)
                    
        if self.has_logp:
            self.attach_extended_parents()
    
    def attach_extended_parents(self):           
        for e_parent in self.owner.extended_parents:
            if isinstance(e_parent, StochasticBase):
                e_parent.extended_children.add(self.owner)
        

    def __setitem__(self, key, new_parent):
        old_parent = self[key]
        
        # Possibly remove owner from old parent's children set.
        if isinstance(old_parent, Variable) or isinstance(old_parent, ContainerBase):
            
            # Tell all extended parents to forget about owner
            if self.has_logp:
                self.detach_extended_parents()
            
            self.val_keys.remove(key)
            self.nonval_keys.append(key)
        
            if isinstance(old_parent, Variable):                
                # See if owner only claims the old parent via this key.
                if sum([parent is old_parent for parent in self.itervalues()]) == 1:
                    old_parent.children.remove(self.owner)
        
                
            if isinstance(old_parent, ContainerBase):
                for variable in old_parent.variables:
                    if sum([parent is variable for parent in self.itervalues()]) == 1:
                        variable.children.remove(self.owner)
                        
                    
                
        # If the new parent is a variable, add owner to its children set.
        if isinstance(new_parent, Variable) or isinstance(new_parent, ContainerBase):
        
            self.val_keys.append(key)
            self.nonval_keys.remove(key)
            
            if isinstance(new_parent, Variable):
                new_parent.children.add(self.owner)
                
            elif isinstance(new_parent, ContainerBase):
                for variable in new_parent.variables:
                    new_parent.children.add(self.owner)
                    
        # Totally recompute extended parents
        self.owner.extended_parents = extend_parents(self.variables)
        if self.has_logp:
            self.attach_extended_parents()
        
        dict.__setitem__(self, key, new_parent)
        file_items(self, self)
        
        # Tell my owner it needs a new lazy function.
        self.owner.gen_lazy_function()

class Potential(PotentialBase):
    """
    Not a variable; just an arbitrary log-probability term to multiply into the 
    joint distribution. Useful for expressing models that aren't directed, such as
    Markov random fields.

    Decorator instantiation:

    @potential(trace = True)
    def A(x = B, y = C):
        return -.5 * (x-y)**2 / 3.

    Direct instantiation:

    :Parameters:

        -logp: function
              The function that computes the potential's value from the values 
              of its parents.

        -doc: string
              The docstring for this potential.

        -name: string
              The name of this potential.

        -parents: dictionary
              A dictionary containing the parents of this potential.

        -cache_depth (optional): integer
              An integer indicating how many of this potential's value computations 
              should be 'memoized'.
              
        - plot (optional) : boolean
            A flag indicating whether this variable is to be plotted.
                                    
        - verbose (optional) : integer
              Level of output verbosity: 0=none, 1=low, 2=medium, 3=high

                            
    Externally-accessible attribute:

        -logp: float
              Returns the potential's log-probability given its parents' values. Skips
              computation if possible.
            
    No methods.
    
    :SeeAlso: Stochastic, Node, LazyFunction, stoch, dtrm, data, Model, Container
    """
    def __init__(self, logp,  doc, name, parents, cache_depth=2, plot=None, verbose=0):
        
        self.ParentDict = ParentDict

        # This function gets used to evaluate self's value.
        self._logp_fun = logp
        
        Node.__init__(  self, 
                        doc=doc, 
                        name=name, 
                        parents=parents, 
                        cache_depth = cache_depth,
                        verbose=verbose)

        self._plot = plot

        self._logp.force_compute()
        
        # Check initial value
        if not isinstance(self.logp, float):
            raise ValueError, "Potential " + self.__name__ + "'s initial log-probability is %s, should be a float." %self.logp.__repr__()

    def gen_lazy_function(self):
        
        self._logp = LazyFunction(fun = self._logp_fun, 
                                    arguments = self.parents, 
                                    ultimate_args = self.extended_parents, 
                                    cache_depth = self._cache_depth)     
        self._logp.force_compute()   

    def get_logp(self):
        if self.verbose > 1:
            print '\t' + self.__name__ + ': log-probability accessed.'
        logp = self._logp.get()
        if self.verbose > 1:
            print '\t' + self.__name__ + ': Returning log-probability ', logp
            
        try:
            logp = float(logp)
        except:
            raise TypeError, self.__name__ + ': computed log-probability ' + str(logp) + ' cannot be cast to float'

        if isnan(logp):
            raise ValueError, self.__name__ + ': computed log-probability is nan'

        # Check if the value is smaller than a double precision infinity:
        if logp <= d_neg_inf:
            raise ZeroProbability, "Potential %s forbids its parents' current values: %s" % (self.__name__, self._parents.value)

        return logp
        
    def set_logp(self,value):      
        raise AttributeError, 'Potential '+self.__name__+'\'s log-probability cannot be set.'

    logp = property(fget = get_logp, fset=set_logp, doc="Self's log-probability value conditional on parents.")

        
class Deterministic(DeterministicBase):
    """
    A variable whose value is determined by the values of its parents.

    Decorator instantiation:

    @dtrm(trace=True)
    def A(x = B, y = C):
        return sqrt(x ** 2 + y ** 2)
    
    :Parameters:
      eval : function
        The function that computes the variable's value from the values 
        of its parents.
      doc : string
        The docstring for this variable.
      name: string
        The name of this variable.
      parents: dictionary
        A dictionary containing the parents of this variable.
      trace (optional): boolean
        A boolean indicating whether this variable's value 
        should be traced (in MCMC).
      cache_depth (optional): integer  
        An integer indicating how many of this variable's
        value computations should be 'memoized'.
      plot (optional) : boolean
        A flag indicating whether this variable is to be plotted.
      verbose (optional) : integer
        Level of output verbosity: 0=none, 1=low, 2=medium, 3=high
                            
    :Attributes:    
      value : any object
        Returns the variable's value given its parents' values. Skips
        computation if possible.
    
    :SeeAlso:
      Stochastic, Potential, deterministic, MCMC, Lambda,
      LinearCombination, Index
    """
    def __init__(self, eval,  doc, name, parents, dtype=None, trace=True, cache_depth=2, plot=None, verbose=0):

        self.ParentDict = ParentDict

        # This function gets used to evaluate self's value.
        self._eval_fun = eval
        
        Variable.__init__(  self, 
                        doc=doc, 
                        name=name, 
                        parents=parents, 
                        cache_depth = cache_depth, 
                        dtype=dtype,
                        trace=trace,
                        plot=plot,
                        verbose=verbose)
                        
        self._value.force_compute()
        
        self._size = size(self.value)
        
    def gen_lazy_function(self):

        self._value = LazyFunction(fun = self._eval_fun, 
                                    arguments = self.parents, 
                                    ultimate_args = self.extended_parents,
                                    cache_depth = self._cache_depth)
                                       
        self._value.force_compute()

    def get_value(self):
        if self.verbose > 1:
            print '\t' + self.__name__ + ': value accessed.'
        _value = self._value.get()
        if isinstance(_value, ndarray):
            _value.flags['W'] = False
        if self.verbose > 1:
            print '\t' + self.__name__ + ': Returning value ',_value
        return _value
        
    def set_value(self,value):      
        raise AttributeError, 'Deterministic '+self.__name__+'\'s value cannot be set.'

    value = property(fget = get_value, fset=set_value, doc="Self's value computed from current values of parents.")


class Stochastic(StochasticBase):
    
    """
    A variable whose value is not determined by the values of its parents.

    
    Decorator instantiation:

    @stoch(trace=True)
    def X(value = 0., mu = B, tau = C):
        return Normal_like(value, mu, tau)
        
    @stoch(trace=True)
    def X(value=0., mu=B, tau=C):

        def logp(value, mu, tau):
            return Normal_like(value, mu, tau)
        
        def random(mu, tau):
            return Normal_r(mu, tau)
            
        rseed = 1.

    
    Direct instantiation:

    

    - logp : function   
            The function that computes the variable's log-probability from
            its value and the values of its parents.

    - doc : string    
            The docstring for this variable.

    - name : string   
            The name of this variable.

    - parents: dict
            A dictionary containing the parents of this variable.
    
    - random (optional) : function 
            A function that draws a new value for this
            variable given its parents' values.

    - trace (optional) : boolean   
            A boolean indicating whether this variable's value 
            should be traced (in MCMC).
                        
    - value (optional) : number or array  
            An initial value for this variable
    
    - dtype (optional) : type
            A type for this variable.
            
    - rseed (optional) : integer or rseed
            A seed for this variable's rng. Either value or rseed must
            be given.
                        
    - isdata (optional) :  boolean
            A flag indicating whether this variable is data; whether
            its value is known.

    - cache_depth (optional) : integer
            An integer indicating how many of this variable's
            log-probability computations should be 'memoized'.
            
    - plot (optional) : boolean
            A flag indicating whether this variable is to be plotted.
                            
    - verbose (optional) : integer
            Level of output verbosity: 0=none, 1=low, 2=medium, 3=high

                            
    Externally-accessible attribute:

    - value: any class
          Returns this variable's current value.

    - logp: float
          Returns the variable's log-probability given its value and its 
          parents' values. Skips computation if possible.
            
    last_value: any class
          Returns this variable's last value. Useful for rejecting
          Metropolis-Hastings jumps. See touch() and the warning below.
            
    Externally-accessible methods:
    
    random():   Draws a new value for this variable from its distribution and
                returns it.
                
    :SeeAlso: Deterministic, Node, LazyFunction, stoch, dtrm, data, Model, Container
    """
    
    def __init__(   self, 
                    logp, 
                    doc, 
                    name, 
                    parents, 
                    random = None, 
                    trace=True, 
                    value=None,
                    dtype=None, 
                    rseed=False, 
                    isdata=False,
                    cache_depth=2,
                    plot=None,
                    verbose = 0):                    

        self.ParentDict = ParentDict

        # A flag indicating whether self's value has been observed.
        self.isdata = isdata
        
        # This function will be used to evaluate self's log probability.
        self._logp_fun = logp
        
        # This function will be used to draw values for self conditional on self's parents.
        self._random = random
        
        # A seed for self's rng. If provided, the initial value will be drawn. Otherwise it's
        # taken from the constructor.
        self.rseed = rseed
        
        # Specify the dimension of stochastic
        self._size = size(value)
        
        if value is not None:
            try:
                self._value = dtype(value)
            except (TypeError,ValueError):
                self._value = asarray(value, dtype=dtype)
        else:
            self._value = None
                
        Variable.__init__(  self, 
                        doc=doc, 
                        name=name, 
                        parents=parents, 
                        cache_depth=cache_depth, 
                        trace=trace,
                        dtype=dtype,
                        plot=plot,
                        verbose=verbose)    
        
        if isinstance(self._value, ndarray) and not dtype is self._value.dtype:
            self._value = asarray(self._value, dtype=dtype).view(self._value.__class__)                
        
        if isinstance(self._value, ndarray):
            self._value.flags['W'] = False
            
        # Check initial value
        if not isinstance(self.logp, float):
            raise ValueError, "Stochastic " + self.__name__ + "'s initial log-probability is %s, should be a float." %self.logp.__repr__()
                
    def gen_lazy_function(self):
        """
        Will be called by Node at instantiation.
        """
        
        # If value argument to __init__ was None, draw value from random method.
        if self._value is None:

            # Use random function if provided
            if self._random is not None:
                self._value = self._random(**self._parents.value)

            # Otherwise leave initial value at None and warn.
            else:
                raise ValueError, 'Stochastic ' + self.__name__ + "'s value initialized to None; no initial value or random method provided."
                
        # Check for missing values
        if not self.__dict__.has_key('_missing'):
            try:
            
                self._missing = [i for i,x in enumerate(self.value) if x==None]
                self._size = len(self._missing)
        
                if self._missing:
            
                    # Use random function if provided
                    if self._random is not None:
                        self._value[self._missing] = self._random(**self._parents.value)[self._missing]

                    # Otherwise leave initial value at None and warn.
                    else:
                        raise ValueError, 'Stochastic ' + self.__name__ + "'s value initialized to None; no initial value or random method provided."
                
            except TypeError:
                self._missing = None
                
        arguments = {}
        arguments.update(self.parents)
        arguments['value'] = self
        arguments = DictContainer(arguments)
        
        self._logp = LazyFunction(fun = self._logp_fun, 
                                    arguments = arguments, 
                                    ultimate_args = self.extended_parents | set([self]),
                                    cache_depth = self._cache_depth)   
        
        self._logp.force_compute()             
    
    def get_value(self):
        # Define value attribute
        
        if self.verbose > 1:
            print '\t' + self.__name__ + ': value accessed.'
        return self._value

    
    def set_value(self, value):
        # Record new value and increment counter
        
        if self.verbose > 0:
            print '\t' + self.__name__ + ': value set to ', value
        
        # Value can't be updated if isdata=True
        if self.isdata:
            if self._missing:
                missing_values = value[self._missing]
                value = copy(self._value)
                value[self._missing] = missing_values
            else:
                raise AttributeError, 'Stochastic '+self.__name__+'\'s value cannot be updated if isdata flag is set'
            
        # Save current value as last_value
        # Don't copy because caching depends on the object's reference. 
        self.last_value = self._value            
        
        if isinstance(value, ndarray):
            value.flags['W'] = False  
            if self.dtype is not None:
                if not self.dtype is value.dtype:
                    self._value = asarray(value, dtype=self.dtype).view(value.__class__)
                else:
                    self._value = value
            else:
                self._value = value
                
        elif self.dtype and self.dtype is not object:
            try:
                self._value = self.dtype(value)
            except TypeError:
                self._value = asarray(value, dtype=self.dtype)
       
        else:
            self._value = value
        

    value = property(fget=get_value, fset=set_value, doc="Self's current value.")
    

    def revert(self):
        """
        Sets self's value to self's last value. Bypasses the data cleaning in
        the set_value method.
        """
        self._value = self.last_value


    def get_logp(self):
        
        if self.verbose > 0:
            print '\t' + self.__name__ + ': logp accessed.'
        logp = self._logp.get()
        
        try:
            logp = float(logp)
        except:
            raise TypeError, self.__name__ + ': computed log-probability ' + str(logp) + ' cannot be cast to float'
        
        if isnan(logp):
            raise ValueError, self.__name__ + ': computed log-probability is nan'
        
        if self.verbose > 0:
            print '\t' + self.__name__ + ': Returning log-probability ', logp
        
        # Check if the value is smaller than a double precision infinity:
        if logp <= d_neg_inf:
            raise ZeroProbability, "Stochastic %s's value is outside its support,\n or it forbids its parents' current values.\nValue: %s\nParents' values:%s" % (self.__name__, self._value, self._parents.value)
    
        return logp

    def set_logp(self):
        raise AttributeError, 'Stochastic '+self.__name__+'\'s logp attribute cannot be set'

    logp = property(fget = get_logp, fset=set_logp, doc="Log-probability or log-density of self's current value\n given values of parents.")        

    
    # Sample self's value conditional on parents.
    def random(self):
        """
        Draws a new value for a stoch conditional on its parents
        and returns it.
        
        Raises an error if no 'random' argument was passed to __init__.
        """
        
        if self._random:
            # Get current values of parents for use as arguments for _random()
            r = self._random(**self.parents.value)
        else:
            raise AttributeError, 'Stochastic '+self.__name__+' does not know how to draw its value, see documentation'
        
        # Set Stochastic's value to drawn value
        self.value = r
            
        return r
    
    # Shortcut alias to random
    rand = random
        
    def _get_coparents(self):
        coparents = set()
        for child in self.extended_children:
            coparents |= child.extended_parents
        coparents.add(self)
        return coparents
    coparents = property(_get_coparents, doc="All the variables whose extended children intersect with self's.")
    
    def _get_moral_neighbors(self):
        moral_neighbors = self.coparents | self.extended_parents | self.extended_children
        for neighbor in copy(moral_neighbors):
            if isinstance(neighbor, PotentialBase):
                moral_neighbors.remove(neighbor)
        return moral_neighbors
    moral_neighbors = property(_get_moral_neighbors, doc="Self's neighbors in the moral graph: self's Markov blanket with self removed.")
    
    def _get_markov_blanket(self):
        return self.moral_neighbors | set([self])
    markov_blanket = property(_get_markov_blanket, doc="Self's coparents, self's extended parents, self's children and self.")
