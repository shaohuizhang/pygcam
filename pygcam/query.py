"""
.. Support for querying GCAM's XML database and processing results.

.. codeauthor:: Rich Plevin <rich@plevin.com>

.. Copyright (c) 2016 Richard Plevin
   See the https://opensource.org/licenses/MIT for license details.

"""
import os
import re
import subprocess
from .utils import getTempFile, TempFile, mkdirs, ensureExtension, saveToFile
from .error import PygcamException, ConfigFileError, FileFormatError, CommandlineError, FileMissingError
from .log import getLogger
from .Xvfb import Xvfb
from .config import getParam, getParamAsBoolean
from .subcommand import SubcommandABC

_logger = getLogger(__name__)

__version__ = '0.2'

GCAM_32_REGIONS = [
    'Africa_Eastern',
    'Africa_Northern',
    'Africa_Southern',
    'Africa_Western',
    'Argentina',
    'Australia_NZ',
    'Brazil',
    'Canada',
    'Central America and Caribbean',
    'Central Asia',
    'China',
    'Colombia',
    'EU-12',
    'EU-15',
    'Europe_Eastern',
    'Europe_Non_EU',
    'European Free Trade Association',
    'India',
    'Indonesia',
    'Japan',
    'Mexico',
    'Middle East',
    'Pakistan',
    'Russia',
    'South Africa',
    'South America_Northern',
    'South America_Southern',
    'South Asia',
    'South Korea',
    'Southeast Asia',
    'Taiwan',
    'USA'
]

def limitYears(df, years):
    """
    Modify df to drop all years outside the range given by `years`.

    :param years: a sequence of two years (str or int); only values in this
        range (inclusive) are kept. Data for other years is dropped.
    :return: (DataFrame) df, modified in place.
    """
    first, last = map(int, years)
    yearCols  = map(int, filter(str.isdigit, df.columns))
    dropYears = map(str, filter(lambda y: y < first or y > last, yearCols))
    df.drop(dropYears, axis=1, inplace=True)
    return df

def interpolateYears(df, startYear=0, inplace=False):
    """
    Interpolate linearly between each pair of years in the GCAM output. The
    timestep is calculated from the numerical (string) column headings given
    in the `DataFrame`_ `df`, which are assumed to represent years in the time-series.
    The years to interpolate between are read from `df`, so there's no dependency
    on any particular time-step, or even on the time-step being constant.

    :param df: (DataFrame) Data of the format returned by batch queries
        on the GCAM XML database
    :param startYear: If non-zero, begin interpolation at this year.
    :param inplace: If True, modify `df` in place; otherwise modify a copy.
    :return: if `inplace` is True, `df` is returned; otherwise a copy
      of `df` with interpolated values is returned.
    """
    yearCols = filter(str.isdigit, df.columns)
    years = map(int, yearCols)

    for i in range(0, len(years)-1):
        start = years[i]
        end   = years[i+1]
        timestep = end - start

        if timestep == 1:       # don't interpolate annual results if already annual
            continue

        startCol = df[str(start)]
        endCol   = df[str(end)]

        # compute vector of annual deltas for each row
        delta = (endCol - startCol)/timestep

        # interpolate the whole column -- but don't interpolate before the start year
        for j in range(1, timestep):
            nextYear = start + j
            df[str(nextYear)] = df[str(nextYear-1)] + (0 if nextYear < startYear else delta)

    yearCols = filter(str.isdigit, df.columns)  # get annualized year columns
    years = map(int, yearCols)       # sort as integers
    years.sort()
    yearCols = map(str, years)       # convert back to strings, now sorted

    nonYearCols = list(set(df.columns) - set(yearCols))
    result = df.reindex_axis(nonYearCols + yearCols, axis=1, copy=(not inplace))
    return result

def readCsv(filename, skiprows=1, years=None, interpolate=False, startYear=0):
    """
    Read a CSV file of the form generated by GCAM batch queries, i.e., skip on
    row and then read column headings and data. Optionally drop all years outside
    the `years` given. Optionally linearly interpolate annual values between
    timesteps.

    :param filename: (str) the path to a CSV file
    :param skiprows: (int) the number of rows to skip before reading the data matrix
    :param years: (iterable of two values coercible to int) the year columns to keep; others are dropped
    :param interpolate: (bool) If True, interpolate annual values between timesteps
    :param startYear: (int) If interpolating, the year to begin interpolation
    :return: (DataFrame) the data read in, optionally processed as per arguments
    """
    import pandas as pd

    _logger.debug("Reading %s", filename)
    try:
        df = pd.read_table(filename, sep=',', skiprows=skiprows, index_col=None)
    except IOError, e:
        raise FileMissingError(os.path.abspath(filename), e)

    if years:
        limitYears(df, years)

    if interpolate:
        df = interpolateYears(df, startYear=startYear)

    return df

def writeCsv(df, filename, header='', float_format="%.4f"):
    'Write a file in "standard" GCAM csv format'
    _logger.debug("Writing %s", filename)

    txt = df.to_csv(None, float_format=float_format)
    with open(filename, 'w') as f:
        f.write("%s\n" % header)  # add a header line to match batch-query output format
        f.write(txt)

def readQueryResult(batchDir, baseline, queryName, years=None, interpolate=False, startYear=0):
    """
    Compose the name of the 'standard' result file, read it into a DataFrame and
    return the DataFrame. Data is read from the computed filename
    "{batchDir}/{queryName}-{baseline}.csv".

    :param batchDir: (str) a directory in which the data file resides
    :param baseline: (str) the name of a baseline scenario
    :param queryName: (str) the name of a batch query.
    :param years: (iterable of two values coercible to int) the year columnss to keep; others are dropped
    :param interpolate: (bool) If True, interpolate annual values between timesteps
    :param startYear: (int) If interpolating, the year to begin interpolation
    :return: (DataFrame) the data in the computed filename.
    """
    pathname = os.path.join(batchDir, '%s-%s.csv' % (queryName, baseline))
    df= readCsv(pathname, years=years, interpolate=interpolate, startYear=startYear)
    return df

def getRegionList(workspace=None):
    """
    Get a list of the defined region names.

    :param workspace: the path to a ``Main_User_Workspace`` directory that
      has the file
      ``input/gcam-data-system/_common/mappings/GCAM_region_names.csv``,
      or ``None``, in which case the value of config variable
      ``GCAM.SourceWorkspace`` (if defined) is used. If `workspace` is
      empty or ``None``, and the config variable ``GCAM.SourceWorkspace`` is
      empty (the default value), the built-in default 32-region list is returned.
    :return: a list of strings with the names of the defined regions
    """
    relpath = 'input/gcam-data-system/_common/mappings/GCAM_region_names.csv'

    workspace = workspace or getParam('GCAM.SourceWorkspace')
    if not workspace:
        return GCAM_32_REGIONS

    path = os.path.join(workspace, relpath)

    _logger.debug("Reading:", path)
    df = readCsv(path, skiprows=3)  # this is a gcam-data-system input file (different format)
    regions = list(df.region)
    return regions

def readRegionMap(filename):
    """
    Read a region map file containing one or more tab-delimited lines of the form
    ``key`` <tab> ``value``, where `key` should be a standard GCAM region and
    `value` the name of the region to map the original to, which can be an
    existing GCAM region or a new name defined by the user.

    :param filename: the name of a file containing region mappings
    :return: a dictionary holding the mappings read from `filename`
    """
    import re
    mapping = {}
    pattern = re.compile('\t+')

    _logger.info("Reading region map '%s'", filename)
    with open(filename) as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if line[0] == '#':
            continue

        tokens = pattern.split(line)
        if len(tokens) != 2:
            raise FileFormatError("Badly formatted line in region map '%s': %s" % (filename, line))

        mapping[tokens[0]] = tokens[1]

    return mapping

def dropExtraCols(df, inplace=True):
    """
    Drop some columns that GCAM queries sometimes return, but which we generally don't need.
    The columns to drop are taken from from the configuration file variable ``GCAM.ColumnsToDrop``,
    which should be a comma-delimited string. The default value is ``scenario,Notes,Date``.

    :param df: a `DataFrame`_ hold the results of a GCAM query.
    :param inplace: if True, modify `df` in-place; otherwise return a modified copy.
    :return: the original `df` (if inplace=True) or the modified copy.
    """
    columns = df.columns
    unnamed = 'Unnamed:'    # extra (empty) columns can sneak in; eliminate them
    dropCols = filter(lambda s: s[0:len(unnamed)] == unnamed, columns)

    varName = 'GCAM.ColumnsToDrop'
    colString = getParam(varName)
    colList = colString and colString.split(',')

    if colString and not colList:
        raise ConfigFileError("The value of %s is '%s'; should be a comma-delimited list of column names")

    unneeded  = set(colList)
    columnSet = set(columns)
    dropCols += columnSet & unneeded    # drop any columns in both sets

    resultDF = df.drop(dropCols, axis=1, inplace=inplace)
    return resultDF

def _findOrCreateQueryFile(title, queryPath, regions, regionMap=None, delete=True):
    '''
    Find a query with the given title either as a file (with .xml extension) or
    within an XML query file by searching queryPath. If the query with "title" is
    found in an XML query file, extract it to generate a batch query file and
    apply it to the given regions.
    '''
    sep = os.path.pathsep           # ';' on Windows, ':' on Unix
    items = queryPath.split(sep)
    for item in items:
        if os.path.isdir(item):
            pathname = os.path.join(item, title + '.xml')
            if os.path.isfile(pathname):
                return pathname
        else:
            from lxml import etree as ET    # lazy import speeds startup

            # Support both Main_Queries-type files and batch query files
            xpathPattern = '/queries/queryGroup/*[@title="{title}"]|/queries/aQuery/*[@title="{title}"]'

            tree = ET.parse(item)
            xpath = xpathPattern.format(title=title)
            elts = tree.xpath(xpath)  # returns empty list or list of elements found

            if elts is None or len(elts) == 0:
                # if the literal search fails, repeat search with all "-" changed to " ".
                altTitle = re.sub('_', ' ', title)
                xpath = xpathPattern.format(title=altTitle)
                elts = tree.xpath(xpath)

            if elts is None or len(elts) == 0:
                # if the literal search fails, repeat search with all "_" changed to " ".
                altTitle = re.sub('-', ' ', title)
                xpath = xpathPattern.format(title=altTitle)
                elts = tree.xpath(xpath)

            if elts is None or len(elts) == 0:
                # if the literal search fails, repeat search with all "-" or "_" changed to " ".
                altTitle = re.sub('[-_]', ' ', title)
                xpath = xpathPattern.format(title=altTitle)
                elts = tree.xpath(xpath)

            if len(elts) == 1:
                elt = elts[0]
                root = ET.Element("queries")
                aQuery = ET.Element("aQuery")
                root.append(aQuery)
                for region in regions:
                    aQuery.append(ET.Element('region', name=region))

                aQuery.append(elt)

                if regionMap:
                    # if a rewrite list exists already, use it, otherwise create it.
                    subtree = ET.ElementTree(element=elt)
                    found = subtree.xpath('//labelRewriteList')
                    if len(found) == 1:
                        rewriteList = found[0]

                        # If there was a hard-coded rewrite for regions, delete it
                        # TBD: TEST THIS
                        found = rewriteList.xpath("./level[@name='region']")
                        for regionElt in found:
                            rewriteList.remove(regionElt)
                    else:
                        # create and inject the element
                        rewriteList = ET.Element('labelRewriteList')
                        elt.append(rewriteList)

                    level = ET.Element('level', name='region')
                    rewriteList.append(level)
                    for fromReg, toReg in regionMap.iteritems():
                        level.append(ET.Element('rewrite', attrib={'from': fromReg, 'to': toReg}))

                tmpFile = getTempFile(suffix='.xml', delete=delete)
                _logger.debug("Writing extracted query for '%s' to tmp file '%s'", title, tmpFile)
                tree = ET.ElementTree(root)
                tree.write(tmpFile, xml_declaration=True, encoding="UTF-8", pretty_print=True)
                return tmpFile

    return None

BatchQueryTemplate = """<?xml version="1.0"?>
<!-- WARNING: this file is automatically generated. Changes may be overwritten. -->
<ModelInterfaceBatch>
    <class name="ModelInterface.ModelGUI2.DbViewer">
        <command name="XMLDB Batch File">
            <scenario name="{scenario}"/>
            <queryFile>{queryFile}</queryFile>
            <outFile>{csvFile}</outFile>
            <xmldbLocation>{xmldb}</xmldbLocation>
            <batchQueryResultsInDifferentSheets>false</batchQueryResultsInDifferentSheets>
            <batchQueryIncludeCharts>false</batchQueryIncludeCharts>
            <batchQuerySplitRunsInDifferentSheets>false</batchQuerySplitRunsInDifferentSheets>
            <batchQueryReplaceResults>true</batchQueryReplaceResults>
        </command>
    </class>
</ModelInterfaceBatch>
"""


def _createJavaCommand(batchFile, redirect):
    jarFile = os.path.normpath(getParam('GCAM.JarFile'))
    javaArgs = getParam('GCAM.JavaArgs')
    javaLibPath = getParam('GCAM.JavaLibPath')
    if javaLibPath:
        javaLibPath = os.path.normpath(javaLibPath) # do this separately to avoid turning "" into "."

    javaLibPathArg = '-Djava.library.path="%s"' % javaLibPath if javaLibPath else ""

    command = 'java %s %s -jar "%s" -b "%s" %s' % (javaArgs, javaLibPathArg, jarFile, batchFile, redirect)
    return command

def _copyToLogFile(logFile, filename, msg=''):
    with open(logFile, 'a') as m:
        with open(filename, 'r') as f:
            m.write(msg)
            map(m.write, f.readlines())

def _deleteFile(filename):
    try:
        os.remove(filename)
    except:
        pass

def runBatchQuery(scenario, queryName, queryPath, outputDir, xmldb=None,
                  csvFile=None, miLogFile=None, regions=None,
                  regionMap=None, noRun=False, noDelete=False):
    """
    Run a query against GCAM's XML database given by `xmldb` (or computed
    from other parameters), optionally saving the results into `outfile`.
    Return the data in a pandas `DataFrame`.

    :param scenario: (str) the name of the scenario to perform the query on
    :param queryName: (str) the name of a query to execute
    :param queryPath: (str) a list of directories or XML filenames, separated
        by a colon (on Unix) or a semi-colon (on Windows)
    :param outputDir: (str) the directory in which to write the .CSV
        with query results
    :param xmldb: (str) the pathname to the XML database to query
    :param csvFile: if None, query results are written to a computed filename.
    :param miLogFile: (str) optional name of a log file to write ModelInterface output to.
    :param regions: (iterable of str) the regions you want to include in the query
    :param regionMap: (dict-like) keys are the names of regions that should be mapped; the
        value is the name of the aggregate region to map into.
    :param noRun: (bool) if True, the command is printed but not executed
    :param noDelete: (bool) if True, temporary files created by this function are
        not deleted (use for debugging)
    :return: (str) the absolute path to the generated .CSV file, or None
    """
    basename = os.path.basename(queryName)
    mainPart, extension = os.path.splitext(basename)   # strip extension, if any

    regions = regions or GCAM_32_REGIONS # set default here so it doesn't mess up doc for this method

    delete = not noDelete

    # Look for both the literal name as given as well as the name with underscores replaced with spaces
    filename = _findOrCreateQueryFile(basename, queryPath, regions, regionMap=regionMap, delete=delete)

    if not filename:
        raise PygcamException("Error: file for query '%s' was not found." % basename)

    if not csvFile:
        csvFile = "%s-%s.csv" % (mainPart, scenario)    # compute default filename
        csvFile = csvFile.replace(' ', '_')             # eliminate spaces for convenience

    csvPath = os.path.abspath(os.path.join(outputDir, csvFile))

    # Create a batch file for ModelInterface to invoke the query on the named
    # scenario, and save the output where specified
    batchFile = getTempFile(suffix='.xml', delete=delete)
    batchFileText = BatchQueryTemplate.format(scenario=scenario, queryFile=filename, csvFile=csvPath, xmldb=xmldb)

    _logger.debug("Creating temporary batch file '%s'", batchFile)
    saveToFile(batchFileText, filename=batchFile)

    _logger.debug("Writing results to: %s", csvPath)

    redirect = ">> %s 2>&1" % miLogFile if miLogFile else ''

    if miLogFile:
        mkdirs(os.path.dirname(miLogFile))
        _copyToLogFile(miLogFile, filename,  "Query file: '%s'\n\n" % filename)
        _copyToLogFile(miLogFile, batchFile, "Batch file: '%s'\n\n" % batchFile)

    command = _createJavaCommand(batchFile, redirect)

    if noRun:
        print command
    else:
        _logger.debug(command)

    if not noRun:
        try:
            if getParamAsBoolean('GCAM.UseVirtualBuffer'):
                with Xvfb():
                    subprocess.call(command, shell=True)
            else:
                subprocess.call(command, shell=True)

            # The java program always exits with 0 status, but when the query fails,
            # it writes an error message to the CSV file. If this occurs, we delete
            # the file.
            try:
                failed = False
                with open(csvPath, 'r') as f:
                    line = f.readline()

                if re.search('java.*Exception', line, flags=re.IGNORECASE):
                    failed = True

            except Exception:
                failed = True

            finally:
                if failed:
                    _logger.error("Query '%s' failed. Deleting '%s'", queryName, csvPath)
                    _deleteFile(csvPath)
        except:
            raise

        finally:
            TempFile.remove(filename,  raiseError=False)
            TempFile.remove(batchFile, raiseError=False)


def ensureCSV(file):
    return ensureExtension(file, '.csv')

def sumYears(files, skiprows=1, interpolate=False):
    csvFiles = map(ensureCSV, files)
    dframes  = map(lambda fname: readCsv(fname, skiprows=skiprows, interpolate=interpolate), csvFiles)

    # TBD: preserve columns that have a single value only? Maybe this collapses into sumYearsByGroup()?
    for df, fname in zip(dframes, csvFiles):
        root, ext = os.path.splitext(fname)
        outFile = root + '-sum' + ext
        yearCols = filter(str.isdigit, df.columns)

        with open(outFile, 'w') as f:
            sums = df[yearCols].sum()
            csvText = sums.to_csv(None)
            f.write("%s\n%s\n" % (outFile, csvText))

# TBD: pass an output directory?
def sumYearsByGroup(groupCol, files, skiprows=1, interpolate=False):
    import numpy as np

    csvFiles = map(ensureCSV, files)
    dframes  = map(lambda fname: readCsv(fname, skiprows=skiprows, interpolate=interpolate), csvFiles)

    for df, fname in zip(dframes, csvFiles):
        units = df['Units'].unique()
        if len(units) != 1:
            raise Exception, "Can't sum results; rows have different units: %s" % units

        root, ext = os.path.splitext(fname)
        name = groupCol.replace(' ', '_')     # eliminate spaces for general convenience
        outFile = '%s-groupby-%s%s' % (root, name, ext)

        cols = [groupCol] + filter(str.isdigit, df.columns)
        grouped = df[cols].groupby(groupCol)
        df2 = grouped.aggregate(np.sum)
        df2['Units'] = units[0]         # add these units to all rows

        with open(outFile, 'w') as f:
            csvText = df2.to_csv(None)
            label = outFile
            f.write("%s\n%s\n" % (label, csvText))

def csv2xlsx(inFiles, outFile, skiprows=0, interpolate=False):
    import pandas as pd

    csvFiles = map(ensureCSV, inFiles)
    # TBD: catch exception on reading bad CSV file; save error and report at the end
    dframes  = map(lambda fname: readCsv(fname, skiprows=skiprows, interpolate=interpolate), csvFiles)

    sheetNum = 1
    outFile = ensureExtension(outFile, '.xlsx')
    with pd.ExcelWriter(outFile, engine='xlsxwriter') as writer:
        workbook = writer.book
        linkFmt = workbook.add_format({'font_color': 'blue', 'underline': True})

        # Create an index sheet
        indexSheet = workbook.add_worksheet('index')
        indexSheet.write_string(0, 1, 'Links to query results')
        maxlen = max(map(len, csvFiles))
        indexSheet.set_column('B:B', maxlen)
        for i, name in enumerate(csvFiles):
            row = i+1
            indexSheet.write(row, 0, row)
            indexSheet.write_url(row, 1, "internal:%d!A1" % row, linkFmt, name)
            #indexSheet.write(row, 1, '=hyperlink("#%d!A1", "%s")' % (row, name), linkFmt)

        for df, fname in zip(dframes, csvFiles):
            sheetName = str(sheetNum)
            sheetNum += 1
            dropExtraCols(df, inplace=True)
            df.to_excel(writer, index=None, sheet_name=sheetName, startrow=3, startcol=0)
            worksheet = writer.sheets[sheetName]
            worksheet.write_string(0, 0, "Filename:")
            worksheet.write_string(0, 1, fname)
            #  =HYPERLINK("#1!A1", "Joe")
            #worksheet.write(1, 0, '=hyperlink("#index!A1", "Back to index")', linkFmt)
            worksheet.write_url(1, 0, "internal:index!A1", linkFmt, "Back to index")


def main(args):
    miLogFile   = getParam('GCAM.ModelInterfaceLogFile')
    outputDir   = args.outputDir or getParam('GCAM.OutputDir')
    workspace   = args.workspace or getParam('GCAM.SandboxRoot')
    xmldb       = args.xmldb     or os.path.join(workspace, 'output', getParam('GCAM.DbFile'))
    queryPath   = args.queryPath or getParam('GCAM.QueryPath')
    regionFile  = args.regionMap or getParam('GCAM.RegionMapFile')
    regions     = args.regions.split(',') if args.regions else GCAM_32_REGIONS
    scenarios   = args.scenario.split(',')
    queryNames  = args.queryName

    _logger.debug("Query names: '%s'", queryNames)

    if not queryNames:
        raise CommandlineError("Error: At least one query name must be specified")

    mkdirs(outputDir)

    xmldb = os.path.abspath(xmldb)

    regionMap = readRegionMap(regionFile) if regionFile else None

    if miLogFile:
        miLogFile = os.path.abspath(miLogFile)
        if os.path.lexists(miLogFile):
            os.unlink(miLogFile)       # remove it, if any, to start fresh

    for scenario in scenarios:
        for queryName in queryNames:
            queryName = queryName.strip()

            if not queryName or queryName[0] == '#':    # allow blank lines and comments
                continue

            if queryName == 'exit':
                _logger.warn('Found "exit"; exiting batch query processing')
                return

            _logger.info("Processing query '%s'", queryName)

            runBatchQuery(scenario, queryName, queryPath, outputDir, xmldb=xmldb,
                          miLogFile=miLogFile, regions=regions, regionMap=regionMap,
                          noRun=args.noRun, noDelete=args.noDelete)


class QueryCommand(SubcommandABC):
    def __init__(self, subparsers):
        kwargs = {'fromfile_prefix_chars' : '@',      # use "@" before value to substitute contents of file as arguments

                  'help' : '''Run one or more GCAM database queries by generating and running the
                  named XML queries.''',

                  'description' : '''Run one or more GCAM database queries by generating and running the
                  named XML queries. The results are placed in a file in the specified
                  output directory with a name composed of the basename of the
                  XML query file plus the scenario name. For example,
                  "gcamtool query -o. -s MyReference,MyPolicyCase liquids-by-region"
                  would generate query results into the files ./liquids-by-region-MyReference.csv
                  and ./liquids-by-region-MyPolicyCase.csv.

                  The named queries are located using the value of config variable GCAM.QueryPath,
                  which can be overridden with the -Q argument. The QueryPath consists of one or
                  more colon-delimited (on Unix) or semicolon-delimited (on Windows)
                  elements that can identify directories or XML files. The
                  elements of QueryPath are searched in order until the named query is found. If
                  a path element is a directory, the filename composed of the query + '.xml' is
                  sought in that directory. If the path element is an XML file, a query with a
                  title matching the query name (first literally, then by replacing '_' and '-'
                  characters with spaces) is sought. Note that query names are case-sensitive.

                  This script populates an initial configuration file in ~/.pygcam.cfg when
                  first run. The config file should be customized as needed, e.g., to set "GcamRoot"
                  to the directory holding your Main_User_Workspace unless it happens to live in
                  ~/GCAM, which is the default value.'''}

        super(QueryCommand, self).__init__('query', subparsers, kwargs)

    def addArgs(self, parser):
        parser.add_argument('queryName', nargs='*',
                            help='''A file or files, each holding an XML query to run. (The ".xml" suffix will be added if needed.)
                                    If an argument is preceded by the "@" sign, it is read and its contents substituted as the
                                    values for this argument. That means you can store queries to run in a file (one per line) and
                                    just reference the file by preceding the filename argument with "@".''')

        parser.add_argument('-d', '--xmldb',
                             help='''The XML database to query (default is value of GCAM.DbFile, in the GCAM.Workspace's
                             "output" directory. Overrides the -w flag.''')

        parser.add_argument('-D', '--noDelete', action="store_true",
                            help='''Don't delete any temporary file created by extracting a query from a query file. Used
                                    mainly for debugging.''')

        parser.add_argument('-R', '--regionMap',
                            help='''A file containing tab-separated pairs of names, the first being a GCAM region
                                    and the second being the name to map this region to. Lines starting with "#" are
                                    treated as comments. Lines without a tab character are also ignored. This arg
                                    overrides the value of config variable GCAM.RegionMapFile.''')

        parser.add_argument('-n', '--noRun', action="store_true",
                            help="Show the command to be run, but don't run it")

        parser.add_argument('-o', '--outputDir',
                             help='Where to output the result (default taken from config parameter "GCAM.OutputDir")')

        parser.add_argument('-Q', '--queryPath',
                            help='''A semicolon-delimited list of directories or filenames to look in to find query files.
                                    Defaults to value of config parameter GCAM.QueryPath''')

        parser.add_argument('-r', '--regions',
                            help='''A comma-separated list of regions on which to run queries found in query files structured
                                    like Main_Queries.xml. If not specified, defaults to querying all 32 regions.''')

        parser.add_argument('-s', '--scenario', default='Reference',
                            help='''A comma-separated list of scenarios to run the query/queries for (default is "Reference")
                                    Note that these refer to a scenarios in the XML database.''')

        parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)

        parser.add_argument('-w', '--workspace', default='',
                            help='''The workspace directory in which to find the XML database.
                                    Defaults to value of config file parameter GCAM.Workspace.
                                    Overridden by the -d flag.''')

        return parser

    def run(self, args, tool):
        main(args)
