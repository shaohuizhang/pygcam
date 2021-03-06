'''
.. Copyright (c) 2016 Richard Plevin
   See the https://opensource.org/licenses/MIT for license details.
'''
from __future__ import print_function
import os
import platform
from pkg_resources import resource_string
from backports import configparser
from .error import ConfigFileError, PygcamException

DEFAULT_SECTION = 'DEFAULT'
USR_CONFIG_FILE = '.pygcam.cfg'
USR_DEFAULTS_FILE = '.pygcam.defaults'

PlatformName = platform.system()

_ConfigParser = None

_ProjectSection = DEFAULT_SECTION


def getSection():
    return _ProjectSection

def setSection(section):
    """
    Set the name of the default config file section to read from.

    :param section: (str) a config file section name.
    :return: none
    """
    global _ProjectSection
    _ProjectSection = section

def configLoaded():
    return bool(_ConfigParser)

def getConfig(reload=False, allowMissing=False):
    """
    Return the configuration object. If one has been created already via
    `readConfigFiles`, it is returned; otherwise a new one is created
    and the configuration files are read. Applications generally do not
    need to use this object directly since the single instance is stored
    internally and referenced by the other API functions.

    :param: reload (bool) if True, instantiate a new global ConfigParser.
    :param: allowMissing (bool) if True, a missing config file is not
       treated as an error. This is used only when generating documentation,
       e.g., on readthedocs.org.
    :return: a `ConfigParser` instance.
    """
    if reload:
        global _ConfigParser
        _ConfigParser = None

    return _ConfigParser or readConfigFiles(allowMissing=allowMissing)


def _readConfigResourceFile(filename, package='pygcam', raiseError=True):
    try:
        data = resource_string(package, filename)
    except IOError:
        if raiseError:
            raise
        else:
            return None

    data = unicode(data)
    _ConfigParser.read_string(data, source=filename)
    return data


_usingMCS = None

def mcsSentinelFile():
    home = getHomeDir()
    path = os.path.join(home, '.use_pygcam_mcs')
    return path

def setUsingMCS(value):
    global _usingMCS
    _usingMCS = value

def usingMCS():
    """
    Check if the user environment is configured to use pygcam.mcs, which requires
    that the file ~/.use_pycam_mcs exists. This lets gcamtool know whether to load
    the corresponding built-in sub-commands.

    :return: (bool) True if user environment indicates to use pygcam-mcs.
    """
    global _usingMCS

    if _usingMCS is None:
        path = mcsSentinelFile()
        setUsingMCS(os.path.exists(path))

    return _usingMCS

def getHomeDir():
    if PlatformName == 'Windows':
        # HOME exists on all Unix-like systems; for Windows it's HOMEPATH or HOMESHARE.
        # If set, we use PYGCAM_HOME to identify the folder with the config file;
        # otherwise, we use HOMESHARE if set, or HOMEPATH, in that order.
        env = os.environ
        homedir = env.get('PYGCAM_HOME') or env.get('HOMESHARE') or env.get('HOMEPATH')
        drive, path = os.path.splitdrive(homedir)
        drive = drive or env.get('HOMEDRIVE') or 'C:'
        home = os.path.realpath(drive + path)
        home = home.replace('\\', '/')            # avoids '\' quoting issues
    else:
        home = os.getenv('HOME')

    return home


def userConfigPath():
    path = os.path.join(getHomeDir(), USR_CONFIG_FILE)
    return path

def configDefaultsPath():
    path = os.path.join(getHomeDir(), USR_DEFAULTS_FILE)
    return path

# def removeDefaultsFile():
#     """
#     If the defaults file exists, delete it. This is done by the
#     'init' sub-command to avoid stale defaults files.
#     """
#     path = configDefaultsPath()
#     if os.path.exists(path):
#         os.remove(path)


_instructions = '''#
# This file describes variables defined by the pygcam code. These
# variables allow you to customize many aspects of pygcam, such as
# file locations, and arguments to various commands. See the
# documentation for the config module for detailed explanations.
#
# Use this file to understand the role of each variable and to copy
# and paste variables into your .pygcam.cfg file, as desired.
#
# The default configuration values are provided herein. There is no
# need to specify these variables in your .pygcam.cfg unless you want
# to override the defaults.
#
# To set a project-specific value to override the defaults for one
# project, create a new section by indicating the project name in
# square brackets. For example for the project PROJECT0, you would
# add [PROJECT0]. All settings after this until the next section
# declaration (or end of file) taken as values for "PROJECT0". The
# "gt" script allows you to identify the project you are operating
# on so that the corresponding values are read from the config file.
#
'''

def writeSystemDefaultsFile(systemDefaults):
    '''
    If the system defaults file (~/pygcam.defaults) doesn't exist,
    write the system defaults to the file. Otherwise, just return.
    '''
    path = configDefaultsPath()
    if os.path.exists(path):
        return

    content = _instructions + systemDefaults

    # Add dynamically generated vars (as "raw" values so the obey user's settings of referenced variables)
    content += "\n# For up-to-date documentation of configuration variables, see the\n"
    content += "# listing at the end of https://pygcam.readthedocs.io/en/latest/config.html\n\n"
    content += "# User's home directory\nHome = %s\n\n" % getParam('Home', raw=True)
    content += "# Name of gcam executable relative to 'exe' dir\nGCAM.Executable = %s\n\n" % getParam('GCAM.Executable', raw=True)
    content += "# Location of ModelInterface jar file\nGCAM.MI.JarFile = %s\n\n" % getParam('GCAM.MI.JarFile', raw=True)
    content += "# Whether to use a virtual display when running ModelInterface\nGCAM.MI.UseVirtualBuffer = %s\n\n" % getParam('GCAM.MI.UseVirtualBuffer', raw=True)
    content += "# Editor command to invoke by 'gt config -e'\nGCAM.TextEditor = %s\n\n" % getParam('GCAM.TextEditor', raw=True)

    if PlatformName == 'Windows':   # convert line endings from '\n' to '\r\n' for Windows
        content = content.replace(r'\n', '\r\n')

    # create a file with the system defaults
    with open(path, 'w') as f:
        f.write(content)

def setMacJavaVars():
    """
    Set the environment vars java uses to locate libraries. If var is
    already set, don't override it. Must be called after config info
    has been read since it references GCAM.RefWorkspace.
    """
    if not os.environ.get('JAVA_LIB'):
        refWorkspace = getParam('GCAM.RefWorkspace')
        javaLib = os.path.join(refWorkspace, 'libs/java/lib')
        os.environ['JAVA_LIB'] = javaLib
        setParam('$JAVA_LIB', javaLib)

def readConfigFiles(allowMissing=False):
    """
    Read the pygcam configuration files, starting with ``pygcam/etc/system.cfg``,
    followed by ``pygcam/etc/{platform}.cfg`` if present. If the environment variable
    ``PYGCAM_SITE_CONFIG`` is defined, its value should be a config file, which is
    read next. Finally, the user's config file, ``~/.pygcam.cfg``, is read. Each
    successive file overrides values for any variable defined in an earlier file.

    :return: a populated ConfigParser instance
    """
    global _ConfigParser

    # Strict mode prevents duplicate sections, which we do not restrict
    _ConfigParser = configparser.ConfigParser(comment_prefixes=('#'),
                                              strict=False,
                                              empty_lines_in_values=False)

    # don't force keys to lower-case: variable names are case sensitive
    _ConfigParser.optionxform = lambda option: option

    home = getHomeDir()
    _ConfigParser.set(DEFAULT_SECTION, 'Home', home)
    _ConfigParser.set(DEFAULT_SECTION, 'User', os.getenv('USER', 'unknown'))

    # Create vars from environment variables as '$' + variable name, as in the shell
    for name, value in os.environ.iteritems():
        value = value.replace(r'%', r'%%')
        _ConfigParser.set(DEFAULT_SECTION, '$' + name, value)

    # Initialize config parser with default values
    systemDefaults = _readConfigResourceFile('etc/system.cfg')

    # Read platform-specific defaults, if defined. No error if file is missing.
    _readConfigResourceFile('etc/%s.cfg' % PlatformName, raiseError=False)

    # if user is working with pygcam.mcs, we load additional defaults.
    if usingMCS():
        _readConfigResourceFile('mcs/etc/mcs.cfg', raiseError=True)

    siteConfig = os.getenv('PYGCAM_SITE_CONFIG')
    if siteConfig:
        try:
            with open(siteConfig) as f:
               _ConfigParser.read_file(f)
        except Exception as e:
            print("WARNING: Failed to read site config file: %s" % e)

    # Customizations are stored in ~/.pygcam.cfg
    usrConfigPath = userConfigPath()

    # os.path.exists doesn't always work on Windows, so just try opening it.
    try:
        with open(usrConfigPath) as f:
           _ConfigParser.read_file(f)

    except IOError:
        if not allowMissing:
            if not os.path.lexists(usrConfigPath):
                raise ConfigFileError("Missing configuration file %s" % usrConfigPath)
            else:
                raise ConfigFileError("Can't read configuration file %s" % usrConfigPath)

    try:
        # Write the system defaults to ~/.pygcam.defaults if necessary
        defaultsPath = configDefaultsPath()
        if not os.path.exists(defaultsPath):
            writeSystemDefaultsFile(systemDefaults)
    except Exception as e:
        if not allowMissing:
            raise ConfigFileError("Failed to write %s: %s" % (defaultsPath, e))

    # Dynamically set (if not defined) GCAM.ProjectName in each section, holding the
    # section (i.e., project) name. If user has set this, the value is unchanged.
    projectNameVar = 'GCAM.ProjectName'
    for section in getSections():
        if not (_ConfigParser.has_option(section, projectNameVar) and   # var must exist
                _ConfigParser.get(section, projectNameVar)):            # and not be blank
            _ConfigParser.set(section, projectNameVar, section)

    projectName = getParam('GCAM.DefaultProject', section=DEFAULT_SECTION)
    if projectName:
        setSection(projectName)

    # Set up JAVA environment if needed
    if PlatformName == 'Darwin':
        setMacJavaVars()

    return _ConfigParser

def getSections():
    return _ConfigParser.sections()

def getConfigDict(section=DEFAULT_SECTION, raw=False):
    """
    Return all variables defined in `section` as a dictionary.

    :param section: (str) the name of a section in the config file
    :param raw: (bool) whether to return raw or interpolated values.
    :return: (dict) all variables defined in the section (which includes
       those defined in DEFAULT.)
    """
    d = {key : value for key, value in _ConfigParser.items(section, raw=raw)}
    return d

def setParam(name, value, section=None):
    """
    Set a configuration parameter in memory.

    :param name: (str) parameter name
    :param value: (any, coerced to str) parameter value
    :param section: (str) if given, the name of the section in which to set the value.
       If not given, the value is set in the established project section, or DEFAULT
       if no project section has been set.
    :return: value
    """
    section = section or getSection()
    _ConfigParser.set(section, name, value)
    return value

def getParam(name, section=None, raw=False, raiseError=True):
    """
    Get the value of the configuration parameter `name`. Calls
    :py:func:`getConfig` if needed.

    :param name: (str) the name of a configuration parameters. Note
       that variable names are case-insensitive. Note that environment
       variables are available using the '$' prefix as in a shell.
       To access the value of environment variable FOO, use getParam('$FOO').

    :param section: (str) the name of the section to read from, which
      defaults to the value used in the first call to ``getConfig``,
      ``readConfigFiles``, or any of the ``getParam`` variants.
    :return: (str) the value of the variable, or None if the variable
      doesn't exist and raiseError is False.
    :raises NoOptionError: if the variable is not found in the given
      section and raiseError is True
    """
    section = section or getSection()

    if not section:
        raise PygcamException('getParam was called without setting "section"')

    if not _ConfigParser:
        getConfig()

    try:
        value = _ConfigParser.get(section, name, raw=raw)

    except configparser.NoSectionError:
        if raiseError:
            raise PygcamException('getParam: unknown section "%s"' % section)
        else:
            return None

    except configparser.NoOptionError:
        if raiseError:
            raise PygcamException('getParam: unknown variable "%s"' % name)
        else:
            return None

    return value

def getParamAsBoolean(name, section=None):
    """
    Get the value of the configuration parameter `name`, coerced
    into a boolean value, where any (case-insensitive) value in the
    set ``{'true','yes','on','1'}`` are converted to ``True``, and
    any value in the set ``{'false','no','off','0'}`` is converted to
    ``False``. Any other value raises an exception.
    Calls :py:func:`getConfig` if needed.

    :param name: (str) the name of a configuration parameters.
    :param section: (str) the name of the section to read from, which
      defaults to the value used in the first call to ``getConfig``,
      ``readConfigFiles``, or any of the ``getParam`` variants.
    :return: (bool) the value of the variable
    :raises: :py:exc:`pygcam.error.ConfigFileError`
    """
    true = ('true', 'yes', 'on', '1')
    false = ('false', 'no', 'off', '0')

    value = getParam(name, section=section)
    value = str(value).lower()

    if value in true:
        return True

    if value in false:
        return False

    raise ConfigFileError("The value of variable '%s' could not converted to boolean." % name)


def getParamAsInt(name, section=None):
    """
    Get the value of the configuration parameter `name`, coerced
    to an integer. Calls :py:func:`getConfig` if needed.

    :param name: (str) the name of a configuration parameters.
    :param section: (str) the name of the section to read from, which
      defaults to the value used in the first call to ``getConfig``,
      ``readConfigFiles``, or any of the ``getParam`` variants.
    :return: (int) the value of the variable
    """
    value = getParam(name, section=section)
    return int(value)

def getParamAsFloat(name, section=None):
    """
    Get the value of the configuration parameter `name` as a
    float. Calls :py:func:`getConfig` if needed.

    :param name: (str) the name of a configuration parameters.
    :param section: (str) the name of the section to read from, which
      defaults to the value used in the first call to ``getConfig``,
      ``readConfigFiles``, or any of the ``getParam`` variants.
    :return: (float) the value of the variable
    """
    value = getParam(name, section=section)
    return float(value)

