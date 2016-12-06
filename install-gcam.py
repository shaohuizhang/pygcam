#!/usr/bin/env python
#
# Install gcam v4.3 on Mac OS X or Linux. Windows to come later...
#
# Author: Rich Plevin
# Created: 10 Nov 2016
#
from __future__ import print_function
import os
import sys
import argparse
import subprocess
import platform

PlatformName = platform.system()

Home = os.environ['HOME'] = os.environ['HOME']
DefaultInstallDir  = os.path.join(Home, 'gcam-v4.3-install-dir')
DefaultDownloadDir = os.path.join(Home, '.gcam-installation-tmp')

def parseArgs():
    parser = argparse.ArgumentParser(description='''Install GCAM on OS X or Linux''')

    parser.add_argument('-d', '--downloadDir', default=DefaultDownloadDir,
                        help='''The directory into which to download the required tar files. Default is %s''' % DefaultDownloadDir)

    parser.add_argument('-i', '--installDir', default=DefaultInstallDir,
                        help='''The directory into which to install GCAM 4.3. Default is %s''' % DefaultInstallDir)

    parser.add_argument('-k', '--keepTarFiles', action='store_true',
                        help='''Keep the downloaded tar files rather than deleting them.''')

    parser.add_argument('-n', '--noRun', action='store_true',
                        help='''Print commands that would be executed, but don't run them.''')

    parser.add_argument('-r', '--reuseTarFiles', action='store_true',
                        help='''Use the already-downloaded tar files rather then retrieving them again.''')

    args = parser.parse_args()
    return args

def run(cmd, ignoreError=False, printOnly=False):
    print(cmd)
    if printOnly:
        return

    status = subprocess.call(cmd, shell=True)

    if not ignoreError and status != 0:
        sys.exit(status)

def curl(url, name, printOnly=False):
    run("curl -L %s -o %s" % (url, name), printOnly=printOnly)

def untar(tarfile, directory='.', printOnly=False):
    tar = '/usr/bin/tar' if PlatformName == 'Darwin' else 'tar'
    run("%s xzf %s -C '%s'" % (tar, tarfile, directory), printOnly=printOnly)

def main():
    args = parseArgs()

    coreTarFile = 'gcam-v4.3.tar.gz'
    dataTarFile = 'data-system.tar.gz'

    downloadPrefix = 'https://github.com/JGCRI/gcam-core/releases/download/gcam-v4.3/'

    coreURL = 'https://github.com/JGCRI/gcam-core/archive/' + coreTarFile
    dataURL = downloadPrefix + dataTarFile

    tarFiles = [coreTarFile, dataTarFile]

    madeDownloadDir = False

    downloadDir = args.downloadDir
    installDir  = args.installDir
    printOnly   = args.noRun

    if not os.path.lexists(downloadDir):
        run('mkdir ' + downloadDir, printOnly=printOnly)
        madeDownloadDir = True

    elif not os.path.isdir(downloadDir):
        print('Specified download dir is not a directory: %s' % downloadDir)
        return -1

    if not printOnly:
        os.chdir(downloadDir)

    if not args.reuseTarFiles:
        curl(coreURL, coreTarFile, printOnly=printOnly)
        curl(dataURL, dataTarFile, printOnly=printOnly)

    if not os.path.isdir(installDir):
        run('mkdir ' + installDir, printOnly=printOnly)

    coreDir = os.path.join(installDir, 'gcam-core-gcam-v4.3')

    untar(os.path.join(downloadDir, coreTarFile), installDir, printOnly=printOnly)
    untar(os.path.join(downloadDir, dataTarFile), coreDir,    printOnly=printOnly)

    if PlatformName == 'Darwin':
        binTarFile = 'mac_binaries.tar.gz'
        binURL = downloadPrefix + binTarFile

        if not args.reuseTarFiles:
            curl(binURL, binTarFile, printOnly=printOnly)

        untar(os.path.join(downloadDir, binTarFile), coreDir, printOnly=printOnly)
        tarFiles.append(binTarFile)

    if printOnly:
        return 0

    print("Installed GCAM into %s" % installDir)

    if args.keepTarFiles:
        print("Keeping tar files in %s" % downloadDir)
    else:
        for tarFile in tarFiles:
            os.remove(tarFile)

        if madeDownloadDir:
            # only remove this dir if we created it
            os.rmdir(downloadDir)

    return 0

sys.exit(main())
