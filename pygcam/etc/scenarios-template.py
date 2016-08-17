from pygcam.config import getParam
from pygcam.log import getLogger
from pygcam.xmlEditor import XMLEditor

_logger = getLogger(__name__)

class Baseline(XMLEditor):
    '''
    XML editing class for a baseline scenario
    '''
    def __init__(self, baseline, scenario, xmlOutputRoot, xmlSrcDir, workspace, subdir):
        scenario = None
        super(Baseline, self).__init__(baseline, scenario, xmlOutputRoot, xmlSrcDir,
                                       workspace, subdir, parent=None)

    def setup(self, args):
        super(Baseline, self).setup(args)

        # Call methods of XMLEditor to setup the baseline scenario
        # Examples:

        # Output GHG emissions annually rather than per time-step
        # self.setClimateOutputInterval(1)

        # Drop default 90% land protection
        # self.dropLandProtection()

        # Adjust solver tolerance to reduce stringency
        # self.setupSolver(solutionTolerance=0.01, broydenTolerance=0.001)


class Policy(XMLEditor):
    '''
    XML editing class for policies that refer to the Baseline defined above.
    '''
    def __init__(self, baseline, scenario, xmlOutputRoot, xmlSrcDir, refWorkspace, subdir):
        parent = Baseline(baseline, scenario, xmlOutputRoot, xmlSrcDir, refWorkspace, subdir)
        super(Policy, self).__init__(baseline, scenario, xmlOutputRoot, xmlSrcDir,
                                           refWorkspace, subdir, parent=parent)

    def setup(self, args):
        super(Policy, self).setup(args)

        baseline = args.baseline
        scenario = args.scenario
        years = args.years
        generate = not args.noGenerate
        resultsDir = args.resultsDir or getParam('GCAM.SandboxDir')
        dynamic = args.dynamic

        # do stuff ...

# Define ClassMap if the mapping from scenario name to
# XML editing class is straightforward.
ClassMap = {
    'base'  : Baseline,
    'scen1' : Policy,
    'scen2' : Policy,
}

# Alternatively define a scenarioMapper function to compute
# class names based on scenario names.
#
# def scenarioMapper(scenario):
#     return ClassMap[scenario]

