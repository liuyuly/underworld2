##~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~##
##                                                                                   ##
##  This file forms part of the Underworld geophysics modelling application.         ##
##                                                                                   ##
##  For full license and copyright information, please refer to the LICENSE.md file  ##
##  located at the project root, or contact the authors.                             ##
##                                                                                   ##
##~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~#~##
import underworld as uw
import underworld._stgermain as _stgermain
import sle
import libUnderworld

class SteadyStateHeat(_stgermain.StgCompoundComponent):
    """
    This class provides functionality for a discrete representation
    of the steady state heat equation.
    
    The class uses a standard Galerkin finite element method to
    construct a system of linear equations which may then be solved 
    using an object of the underworld.system.Solver class.
    
    The underlying element types are determined by the supporting 
    mesh used for the 'temperatureField'.

    .. math::
         \nabla { ( k \nabla \phi } ) = h

    where, k is the diffusivity, T is the temperature, h is
    a source term.

    Parameters
    ----------
    temperatureField : underworld.mesh.MeshVariable
        The solution field for temperature.
    fn_diffusivity : underworld.function.Function
        The conductivy function that defines the diffusivity across the domain.
    fn_heating : underworld.function.Function, default=0.
        The heating function that defines the heating across the domain.

    Notes
    -----
    Constructor must be called by collectively all processes.

    Example
    -------
    Setup a basic thermal system:
    
    >>> linearMesh = uw.mesh.FeMesh_Cartesian( elementType='Q1/dQ0', elementRes=(4,4), minCoord=(0.,0.), maxCoord=(1.,1.) )
    >>> tField = uw.mesh.MeshVariable( linearMesh, 1 )
    >>> topNodes = linearMesh.specialSets["MaxJ_VertexSet"]
    >>> bottomNodes = linearMesh.specialSets["MinJ_VertexSet"]
    >>> tbcs = uw.conditions.DirichletCondition(tField, topNodes + bottomNodes)
    >>> tField.data[topNodes.data] = 0.0
    >>> tField.data[bottomNodes.data] = 1.0
    >>> tSystem = uw.systems.SteadyStateHeat(temperatureField=tField, fn_diffusivity=1.0, conditions=[tbcs])

    """
    _objectsDict = {  "_system" : "Energy_SLE" }
    _selfObjectName = "_system"

    def __init__(self, temperatureField, fn_diffusivity, fn_heating=0., swarm=None, conditions=[], conductivityFn=None, heatingFn=None, rtolerance=None, **kwargs):
        if conductivityFn:
            raise RuntimeError("Note that the 'conductivityFn' parameter has been renamed to 'fn_diffusivity'.")
        if heatingFn:
            raise RuntimeError("Note that the 'heatingFn' parameter has been renamed to 'fn_heating'.")
        if rtolerance:
            raise RuntimeError("Note that the 'rtolerance' parameter has been removed.\n" \
                               "All solver functionality has been moved to underworld.systems.Solver.")

        if not isinstance( temperatureField, uw.mesh.MeshVariable):
            raise TypeError( "Provided 'temperatureField' must be of 'MeshVariable' class." )
        self._temperatureField = temperatureField

        try:
            _fn_diffusivity = uw.function.Function._CheckIsFnOrConvertOrThrow(fn_diffusivity)
        except Exception as e:
            raise uw._prepend_message_to_exception(e, "Exception encountered. Note that provided 'fn_diffusivity' must be of or convertible to 'Function' class.\nEncountered exception message:\n")

        try:
            _fn_heating = uw.function.Function._CheckIsFnOrConvertOrThrow(fn_heating)
        except Exception as e:
            raise uw._prepend_message_to_exception(e, "Exception encountered. Note that provided 'fn_heating' must be of or convertible to 'Function' class.\nEncountered exception message:\n")

        if swarm and not isinstance(swarm, uw.swarm.Swarm):
            raise TypeError( "Provided 'swarm' must be of 'Swarm' class." )
        self._swarm = swarm

        if not isinstance(conditions, (uw.conditions._SystemCondition, list, tuple) ):
            raise TypeError( "Provided 'conditions' must be a list '_SystemCondition' objects." )
        if len(conditions) > 1:
            raise ValueError( "Multiple conditions are not currently supported." )
        for cond in conditions:
            if not isinstance( cond, uw.conditions._SystemCondition ):
                raise TypeError( "Provided 'conditions' must be a list '_SystemCondition' objects." )
            # set the bcs on here.. will rearrange this in future. 
            if cond.variable == self._temperatureField:
                libUnderworld.StgFEM.FeVariable_SetBC( self._temperatureField._cself, cond._cself )

        # ok, we've set some bcs, lets recreate eqnumbering
        libUnderworld.StgFEM._FeVariable_CreateNewEqnNumber( self._temperatureField._cself )
        self._conditions = conditions

        # create solutions vector
        self._temperatureSol = sle.SolutionVector(temperatureField)

        # create force vectors
        self._fvector = sle.AssembledVector(temperatureField)

        # and matrices
        self._kmatrix = sle.AssembledMatrix( temperatureField, temperatureField, rhs=self._fvector )

        # create swarm
        self._gaussSwarm = uw.swarm.GaussIntegrationSwarm(self._temperatureField.mesh)
        self._PICSwarm = None
        if self._swarm:
            self._PICSwarm = uw.swarm.PICIntegrationSwarm(self._swarm)

        swarmguy = self._PICSwarm
        if not swarmguy:
            swarmguy = self._gaussSwarm
        self._kMatTerm = sle.MatrixAssemblyTerm_NA_i__NB_i__Fn(  integrationSwarm=swarmguy,
                                                                 assembledObject=self._kmatrix,
                                                                 fn=_fn_diffusivity)
        self._forceVecTerm = sle.VectorAssemblyTerm_NA__Fn(   integrationSwarm=swarmguy,
                                                              assembledObject=self._fvector,
                                                              fn=fn_heating)
        super(SteadyStateHeat, self).__init__(**kwargs)


    def _add_to_stg_dict(self,componentDictionary):
        # call parents method
        super(SteadyStateHeat,self)._add_to_stg_dict(componentDictionary)

        componentDictionary[ self._cself.name ][      "StiffnessMatrix"] = self._kmatrix._cself.name
        componentDictionary[ self._cself.name ][       "SolutionVector"] = self._temperatureSol._cself.name
        componentDictionary[ self._cself.name ][          "ForceVector"] = self._fvector._cself.name
        componentDictionary[ self._cself.name ][    "killNonConvergent"] = False
        componentDictionary[ self._cself.name ][           "SLE_Solver"] = None

    def solve(self, *args, **kwargs):
        """ deprecated method
        """
        raise RuntimeError("This method is now deprecated. You now need to explicitly\n"\
                           "create a solver, and then solve it:\n\n"\
                           "    solver = uw.system.Solver(heatSystemObject)\n"\
                           "    solver.solve() \n\n"\
                           "but note that you only need to create the solver once.")

    @property
    def fn_diffusivity(self):
        """
        The diffusivity function. You may change this function directly via this
        property.
        """
        return self._kMatTerm.fn
    @fn_diffusivity.setter
    def fn_diffusivity(self, value):
        self._kMatTerm.fn = value

    @property
    def fn_heating(self):
        """
        The heating function. You may change this function directly via this
        property.
        """
        return self._forceVecTerm.fn
    @fn_heating.setter
    def fn_heating(self, value):
        self._forceVecTerm.fn = value

