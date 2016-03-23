'''
.. Plug-in management system for sub-commands to gcamtool

.. codeauthor:: Rich Plevin <rich@plevin.com>

.. Copyright (c) 2016 Richard Plevin
   See the https://opensource.org/licenses/MIT for license details.
'''
import os
from glob import glob
from abc import ABCMeta, abstractmethod
from pygcam.common import loadModuleFromPath
from pygcam.error import PygcamException

BuiltinSubCommands = []

class PluginBase(object):
    """
    Abstract base class for sub-commands. Defines the protocol expected by ``gcamtool``
    for defining sub-commands. Plugin files should be named ``'*_plugin.py'`` and must
    define a subclass of ``PluginBase``. To allow the class to be identified, it can be
    named ``Plugin`` or the global variable ``PluginClass`` can identify the class.

    :param name: (str) the name of the sub-command
    :param kwargs: (dict) keywords to pass to the the call to argparse's
       ``subparsers.add_parser(name, **kwargs)``, e.g., to pass `help` or
       `documentation` strings.
    :param subparsers: an object returned by argparse's ``parser.add_subparsers()``
    """
    __metaclass__ = ABCMeta

    Parsers = {}

    @classmethod
    def getParser(cls, name):
        return cls.Parsers[name]

    def __init__(self, name, kwargs, subparsers):
        self.name = name
        self.parser = subparsers.add_parser(self.name, **kwargs)
        self.Parsers[self.name] = self.parser
        self.addArgs()

    @abstractmethod
    def addArgs(self):
        pass

    @abstractmethod
    def run(self, args, tool):
        """
        Perform the function intented by the ``PluginBase`` subclass. This function
        is invoked by ``gcamtool`` on the ``PluginBase`` instance whose name matches the
        given sub-command.

        :param args: the argument dictionary
        :param tool: the instantiated pygcam.gcamtool.GcamTool
        :return: nothing
        """
        pass


class PluginManager(object):
    """
    Finds and loads Plugins.

    :param dirs: (sequence of str) directories to search for files
       whose names match the pattern ``'*_plugin.py'``. All such
       files are loaded.
    :param path: (str) a semi-colon-delimited string where each element
       identifies a directory which is then treated as described above
       for the `dirs` argument.
    """
    Instances = {}          # Deprecated?

    @classmethod
    def getPlugin(cls, name):
        return cls.Instances.get(name, None)

    def __init__(self, dirs=[], path=None):
        items = path.split(';') if path else []     # TBD: document use of ';' rather than ':'

        moduleDir = os.path.dirname(os.path.abspath(__file__))
        pluginDir = os.path.join(moduleDir, 'plugins')

        self.pluginDirs = dirs + items + [pluginDir]
        self.plugins = None

    def loadPlugin(self, path, subparsers):
        """
        Load the plugin at `path`.

        :param path: (str) the pathname of a plugin file.
        :param subparsers: instance of argparse.parser.add_subparsers
        :return: an instance of the ``PluginBase`` subclass defined in `path`
        """
        def getModObj(mod, name):
            return getattr(mod, name) if name in mod.__dict__ else None

        mod = loadModuleFromPath(path)
        pluginClass = getModObj(mod, 'PluginClass') or getModObj(mod, 'Plugin')
        if not pluginClass:
            raise PygcamException('Neither PluginClass nor class Plugin are defined in %s' % path)

        plugin = pluginClass(subparsers)
        self.Instances[plugin.name] = plugin

    def loadPlugins(self, subparsers):
        """
        Load plugins from the list of directories calculated in
        ``PluginBase.__init__()`` and instantiate them.

        :return: None
        """
        plugins = []
        for d in self.pluginDirs:
            pattern = os.path.join(d, '*_plugin.py')
            plugins += map(lambda path: self.loadPlugin(path, subparsers), glob(pattern))

        self.plugins = plugins
