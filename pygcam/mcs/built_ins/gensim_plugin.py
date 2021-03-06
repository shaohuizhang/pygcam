# Copyright (c) 2016  Richard Plevin
# See the https://opensource.org/licenses/MIT for license details.

# python 3 compatibility version
from six.moves import xrange
import os
from pygcam.config import getParam, setParam
from pygcam.log import getLogger
from pygcam.utils import mkdirs
from ..context import getSimDir
from .McsSubcommandABC import McsSubcommandABC

_logger = getLogger(__name__)

def genSALibData(trials, method, paramFileObj, args):
    from ..error import PygcamMcsUserError
    from ..sensitivity import DFLT_PROBLEM_FILE, Sobol, FAST, Morris # , MonteCarlo
    from pygcam.utils import ensureExtension, removeTreeSafely, mkdirs, pathjoin

    SupportedDistros = ['Uniform', 'LogUniform', 'Triangle', 'Linked']

    outFile = args.outFile or os.path.join(getSimDir(args.simId), 'data.sa')
    outFile = ensureExtension(outFile, '.sa')

    if os.path.lexists(outFile):
        # Attempt to mv an existing version of the file to the same name with '~'
        backupFile = outFile + '~'
        if os.path.isdir(backupFile):
            removeTreeSafely(backupFile)

        elif os.path.lexists(backupFile):
            raise PygcamMcsUserError("Refusing to delete '%s' since it's not a file package." % backupFile)

        os.rename(outFile, backupFile)

    mkdirs(outFile)

    linked = []

    problemFile = pathjoin(outFile, DFLT_PROBLEM_FILE)
    with open(problemFile, 'w') as f:
        f.write('name,low,high\n')

        for elt in paramFileObj.tree.iterfind('//Parameter'):
            name = elt.get('name')
            distElt = elt.find('Distribution')
            distSpec = distElt[0]   # should have only one child as per schema
            distName = distSpec.tag

            # These 3 distro forms specify min and max values, which we use with SALib
            legal = SupportedDistros + ['Linked']
            if distName not in legal:
                raise PygcamMcsUserError("Found '%s' distribution; must be one of %s for use with SALib." % (distName, legal))

            if distName == 'Linked':        # TBD: ignore these and figure it out when loading the file?
                linked.append((name, distSpec.get('parameter')))
                continue

            # Parse out the various forms: (max, min), (factor), (range), and factor for LogUniform
            attrib = distSpec.attrib
            if 'min' in attrib and 'max' in attrib:
                minValue = float(attrib['min'])
                maxValue = float(attrib['max'])
            elif 'factor' in attrib:
                value = float(attrib['factor'])
                if distName == 'LogUniform':
                    minValue = 1/value
                    maxValue = value
                else:
                    minValue = 1 - value
                    maxValue = 1 + value
            elif 'range' in attrib:
                value = float(attrib['range'])
                minValue = -value
                maxValue =  value

            f.write("%s,%f,%f\n" % (name, minValue, maxValue))

    methods = (Sobol, FAST, Morris) # , MonteCarlo)
    methodMap = {cls.__name__.lower(): cls for cls in methods}

    cls = methodMap[method]
    sa = cls(outFile)

    # saves to input.csv in file package
    sa.sample(trials=trials, calc_second_order=args.calcSecondOrder)
    return sa.inputsDF


def genTrialData(simId, trials, paramFileObj, args):
    """
    Generate the given number of trials for the given simId, using the objects created
    by parsing parameters.xml. Return a DataFrame of values.
    """
    from pandas import DataFrame
    from ..distro import linkedDistro
    from ..LHS import lhs, lhsAmend
    from ..XMLParameterFile import XMLRandomVar, XMLCorrelation
    from ..util import writeTrialDataFile

    rvList = XMLRandomVar.getInstances()

    linked = filter(lambda obj: obj.param.dataSrc.isLinked(), rvList)

    method = args.method
    if method == 'montecarlo':
        # legacy Monte Carlo method. Supporting numerous distributions and correlations.

        corrMatrix = XMLCorrelation.corrMatrix()

        # TBD: this is currently broken. Only "shared" RVs are supported with the DataFrame
        # TBD: approach since a Parameter can have multiple RVs which appear as separate
        # TBD: data columns. This is ok for the current analysis, but needs to be rewritten
        # TBD: on integration with pygcam. (getName() will fail on XMLVariable instances)

        paramNames = map(lambda obj: obj.getParameter().getName(), rvList)
        trialData = lhs(rvList, trials, corrMat=corrMatrix, columns=paramNames, skip=linked)
        writeTrialDataFile(simId, trialData)
    else:
        # SALib methods
        trialData = genSALibData(trials, method, paramFileObj, args)

    linkedDistro.storeTrialData(trialData)  # so its ppf() can access linked values
    lhsAmend(trialData, linked, trials)

    df = DataFrame(data=trialData)
    return df


def saveTrialData(df, simId, start=0):
    """
    Save the trial data in `df` to the SQL database, for the given simId.
    """
    from ..Database import getDatabase
    from ..XMLParameterFile import XMLRandomVar

    trials = df.shape[0]

    # Delete all Trial entries for this simId and this range of trialNums
    db = getDatabase()

    paramValues = []

    for trial in xrange(trials):
        trialNum = trial + start

        # Save all RV values to the database
        instances = XMLRandomVar.getInstances()
        for var in instances:
            varNum = var.getVarNum()
            param = var.getParameter()
            pname = param.getName()
            value = df[pname][trial]
            paramId = db.getParamId(pname)
            paramValues.append((trialNum, paramId, value, varNum))

    # Write the tuples (simId, trialNum, paramId, value) to the database
    db.saveParameterValues(simId, paramValues)

    # SALib methods may not create exactly the number of trials requested
    # so we update the database to set the record straight.
    db.updateSimTrials(simId, trials)
    _logger.info('Generated %d trials for simId %d', trials, simId)


def runStaticSetup(runWorkspace, project, groupName):
    """
    Run the --staticOnly setup in the MCS copy of the workspace, for all scenarios.
    This is called from gensim, so we fake the "context" for trial 0, since all
    trials have local-xml symlinked to RunWorkspace's local-xml.
    """
    import pygcam.tool
    from pygcam.utils import mkdirs
    from pygcam.constants import LOCAL_XML_NAME
    from ..util import symlink
    from ..error import GcamToolError

    projectName = project.projectName

    scenarios = project.getKnownScenarios()
    scenariosArg = ','.join(scenarios)

    useGroupDir = project.scenarioGroup.useGroupDir
    groupSubdir = groupName if useGroupDir else ''

    # create symlinks from all the scenarios' local-xml dirs to shared one
    # under {projectName}/Workspace
    sandboxDir = os.path.join(runWorkspace, groupSubdir)
    mkdirs(sandboxDir)

    wsXmlDir = os.path.join(runWorkspace, LOCAL_XML_NAME)
    mkdirs(wsXmlDir)

    for scenario in scenarios:
        dirname = os.path.join(sandboxDir, scenario)
        mkdirs(dirname)
        linkname  = os.path.join(dirname, LOCAL_XML_NAME)
        symlink(wsXmlDir, linkname)

    # N.B. RunWorkspace for gensim is pygcam's RefWorkspace
    toolArgs = ['+P', projectName, '--mcs=gensim', 'run', '-s', 'setup',
                '-S', scenariosArg, '--sandboxDir=' + sandboxDir]

    if useGroupDir:
        toolArgs += ['-g', groupName]

    _logger.debug('Running: %s', 'gt ' + ' '.join(toolArgs))
    status = pygcam.tool.main(argv=toolArgs, raiseError=True)

    if status != 0:
        msg = '"gt setup" exited with status %d' % status
        raise GcamToolError(msg)

    return status


def genSimulation(simId, trials, paramPath, args):
    '''
    Generate a simulation based on the given parameters.
    '''
    from ..context import Context
    from ..Database import getDatabase
    from ..XMLParameterFile import XMLParameterFile
    from ..util import getSimParameterFile, getSimResultFile, symlink, filecopy
    from pygcam.constants import LOCAL_XML_NAME
    from pygcam.project import Project
    from pygcam.xmlSetup import ScenarioSetup

    runInputDir = getParam('MCS.RunInputDir')
    runWorkspace = getParam('MCS.RunWorkspace')

    # Add symlink to workspace's input dir so we can find XML files using rel paths in config files
    simDir = getSimDir(simId, create=True)
    simInputDir = os.path.join(simDir, 'input')
    symlink(runInputDir, simInputDir)

    # Ditto for workspace's local-xml
    workspaceLocalXml = os.path.join(runWorkspace, LOCAL_XML_NAME)
    simLocalXmlDir = os.path.join(simDir, LOCAL_XML_NAME)
    symlink(workspaceLocalXml, simLocalXmlDir)

    projectName = getParam('GCAM.ProjectName')
    project = Project.readProjectFile(projectName, groupName=args.groupName)

    args.groupName = groupName = args.groupName or project.scenarioSetup.defaultGroup

    # Run static setup for all scenarios in the given group
    runStaticSetup(runWorkspace, project, groupName)

    # TBD: Use pygcam scenario def and copy pygcam files, too
    scenarioFile = getParam('GCAM.ScenarioSetupFile')
    scenarioSetup = ScenarioSetup.parse(scenarioFile)
    scenarioNames = scenarioSetup.scenariosInGroup(groupName)
    baseline      = scenarioSetup.baselineForGroup(groupName)

    # Copy the user's results.xml file to {simDir}/app-xml
    userResultFile = getParam('MCS.ResultsFile')
    simResultFile = getSimResultFile(simId)
    mkdirs(os.path.dirname(simResultFile))
    filecopy(userResultFile, simResultFile)

    if not trials:
        _logger.warn("Simulation meta-data has been copied.")
        return

    # Define the experiments (scenarios) in the database
    db = getDatabase()
    db.addExperiments(scenarioNames, baseline, scenarioFile)

    context = Context(projectName=args.projectName, simId=simId, groupName=groupName)

    paramFileObj = XMLParameterFile(paramPath)
    paramFileObj.loadInputFiles(context, scenarioNames, writeConfigFiles=True)
    paramFileObj.runQueries()

    _logger.info("Generating %d trials to %r", trials, simDir)
    df = genTrialData(simId, trials, paramFileObj, args)

    # Save generated values to the database for post-processing
    saveTrialData(df, simId)

    # Also save the param file as parameters.xml, for reference only
    simParamFile = getSimParameterFile(simId)
    filecopy(paramPath, simParamFile)


def _newsim(runDir):
    '''
    Setup the app and run directories for a given user app.
    '''
    import pkgutil

    from pygcam.scenarioSetup import copyWorkspace
    from pygcam.utils import mkdirs
    from ..Database import getDatabase
    from ..error import PygcamMcsUserError
    from ..XMLResultFile import XMLResultFile

    if not runDir:
        raise PygcamMcsUserError("RunRoot was not set on command line or in configuration file")

    # Create the run dir, if needed
    mkdirs(runDir)

    srcDir = getParam('GCAM.RefWorkspace')
    dstDir = getParam('MCS.RunWorkspace')

    copyWorkspace(dstDir, refWorkspace=srcDir, forceCreate=True, mcsMode=True)

    db = getDatabase()   # ensures database initialization
    XMLResultFile.addOutputs()

    # Load SQL script to create convenient views
    text = pkgutil.get_data('pygcam', 'mcs/etc/views.sql')
    db.executeScript(text=text)


def driver(args, tool):
    '''
    Generate a simulation. Do generic setup, then call genSimulation().
    '''
    from pygcam.utils import removeTreeSafely
    from ..Database import getDatabase
    from ..util import saveDict

    projectName = args.projectName
    runRoot = args.runRoot
    if runRoot:
        # TBD: write this to config file under [project] section
        setParam('MCS.Root', runRoot, section=projectName)
        _logger.info('Please add "MCS.Root = %s" to your .pygcam.cfg file in the [%s] section.',
                     runRoot, projectName)

    runDir = getParam('MCS.RunDir', section=projectName)

    if args.delete:
        removeTreeSafely(runDir, ignore_errors=False)

    if not os.path.exists(runDir):
        _newsim(runDir)

    simId  = args.simId
    trials = args.trials
    desc   = args.desc

    # The simId can be provided on command line, in which case we need
    # to delete existing parameter entries for this app and simId.
    db = getDatabase()
    simId = db.createSim(trials, desc, simId=simId)

    paramFile = args.paramFile or getParam('MCS.ParametersFile')
    genSimulation(simId, trials, paramFile, args=args)

    # Save a copy of the arguments used to create this simulation
    simDir = getSimDir(simId)
    argSaveFile = '%s/gcamGenSimArgs.txt' % simDir
    saveDict(vars(args), argSaveFile)


class GensimCommand(McsSubcommandABC):

    def __init__(self, subparsers):
        kwargs = {'help' : 'Generate input files for simulations.'}
        super(GensimCommand, self).__init__('gensim', subparsers, kwargs)

    def addArgs(self, parser):
        parser.add_argument('--delete', action='store_true',
                            help='''DELETE and recreate the simulation "run" directory.''')

        parser.add_argument('-D', '--desc', type=str, default='',
                            help='A brief (<= 256 char) description the simulation.')

        parser.add_argument('-g', '--groupName', default='',
                            help='''The name of a scenario group to process.''')

        parser.add_argument('-m', '--method', choices=['montecarlo', 'sobol', 'fast', 'morris'],
                            default='montecarlo',
                            help='''Use the specified method to generate trial data. Default is "montecarlo".''')

        parser.add_argument('-o', '--outFile',
                            help='''For methods other than "montecarlo". The path to a "package 
                            directory" into which SALib-related data are stored.
                            If the filename does not end in '.sa', this extension is added. The file
                            'problem.csv' within the package directory will contain the parameter specs in
                            SALib format. The file inputs.csv is also generated in the file package using
                            the chosen method's sampling method. If an outFile is not specified, a package
                            of the name 'data.sa' is created in the simulation run-time directory.''')

        parser.add_argument('-p', '--paramFile', default=None,
                            help='''Specify an XML file containing parameter definitions.
                            Defaults to the value of config parameter MCS.ParametersFile
                            (currently %s)''' % getParam('MCS.ParametersFile'))

        runRoot = getParam('MCS.Root')
        parser.add_argument('-r', '--runRoot', default=None,
                            help='''Root of the run-time directory for running user programs. Defaults to
                            value of config parameter MCS.Root (currently %s)''' % runRoot)

        parser.add_argument('-S', '--calcSecondOrder', action='store_true',
                            help='''For Sobol method only -- calculate second-order sensitivities.''')

        parser.add_argument('-s', '--simId', type=int, default=1,
                            help='The id of the simulation. Default is 1.')

        parser.add_argument('-t', '--trials', type=int, required=True,
                            help='The number of trials to create for this simulation (REQUIRED)')

        return parser   # for auto-doc generation


    def run(self, args, tool):
        driver(args, tool)
