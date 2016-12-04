#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
## Python to interface with MyQ garage doors.
## based on https://github.com/Einstein42/myq-garage

import sys
import time
import logging

from ghpu import GitHubPluginUpdater

kCurDevVersCount = 0        # current version of plugin devices

################################################################################
class Plugin(indigo.PluginBase):

    ########################################
    # Main Plugin methods
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = " + str(self.logLevel))


    def startup(self):
        indigo.server.log(u"Starting Masquerade")

        self.masqueradeList = {}

        self.updater = GitHubPluginUpdater(self)
        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "24")) * 60.0 * 60.0
        self.logger.debug(u"updateFrequency = " + str(self.updateFrequency))
        self.next_update_check = time.time()

        indigo.devices.subscribeToChanges()


    def shutdown(self):
        indigo.server.log(u"Shutting down Masquerade")


    def runConcurrentThread(self):

        try:
            while True:

                if self.updateFrequency > 0:
                    if time.time() > self.next_update_check:
                        self.updater.checkForUpdate()
                        self.next_update_check = time.time() + self.updateFrequency

                self.sleep(60.0)

        except self.stopThread:
            pass

    def deviceStartComm(self, device):

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        if instanceVers >= kCurDevVersCount:
            self.logger.debug(device.name + u": Device Version is up to date")
        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps

            newProps["devVersCount"] = kCurDevVersCount
            device.replacePluginPropsOnServer(newProps)
            self.logger.debug(u"Updated " + device.name + " to version " + str(kCurDevVersCount))
        else:
            self.logger.error(u"Unknown device version: " + str(instanceVers) + " for device " + device.name)

        self.logger.debug("Adding Device %s (%d) to device list" % (device.name, device.id))
        assert device.id not in self.masqueradeList
        self.masqueradeList[device.id] = device

    def deviceStopComm(self, device):
        self.logger.debug("Removing Device %s (%d) from device list" % (device.name, device.id))
        assert device.id in self.masqueradeList
        del self.masqueradeList[device.id]


    ########################################
    # Menu Methods
    ########################################

    def checkForUpdates(self):
        self.updater.checkForUpdate()

    def updatePlugin(self):
        self.updater.update()

    def forceUpdate(self):
        self.updater.update(currentVersion='0.0.0')

    ########################################
    # ConfigUI methods
    ########################################

    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorDict = indigo.Dict()

        updateFrequency = int(valuesDict['updateFrequency'])
        if (updateFrequency < 0) or (updateFrequency > 24):
            errorDict['updateFrequency'] = u"Update frequency is invalid - enter a valid number (between 0 and 24)"

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)

        return (True, valuesDict)


    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"logLevel = " + str(self.logLevel))

            self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "24")) * 60.0 * 60.0
            self.logger.debug(u"updateFrequency = " + str(self.updateFrequency))
            self.next_update_check = time.time()

    ################################################################################
    #
    # delegate methods for indigo.devices.subscribeToChanges()
    #
    ################################################################################

    def deviceDeleted(self, delDevice):
        indigo.PluginBase.deviceDeleted(self, delDevice)

        for myDeviceId, myDevice in sorted(self.masqueradeList.iteritems()):
            baseDevice = int(myDevice.pluginProps["baseDevice"])
            if delDevice.id == baseDevice:
                self.logger.info(u"A device (%s) that was being Masqueraded has been deleted.  Disabling %s" % (delDevice.name, myDevice.name))
                indigo.device.enable(myDevice, value=False)   #disable it


    def deviceUpdated(self, oldDevice, newDevice):
        indigo.PluginBase.deviceUpdated(self, oldDevice, newDevice)

        for myDeviceId, myDevice in sorted(self.masqueradeList.iteritems()):
            baseDevice = int(myDevice.pluginProps["baseDevice"])
            if oldDevice.id == baseDevice:
                masqState = myDevice.pluginProps["masqState"]
                matchString = myDevice.pluginProps["matchString"]
                reverse = bool(myDevice.pluginProps["reverse"])

                if oldDevice.states[masqState] != newDevice.states[masqState]:
                    match = (str(newDevice.states[masqState]) == matchString)
                    if reverse:
                        match = not match
                    self.logger.debug(u"%s, a masqueraded device, has been updated: %s (%s)." % (oldDevice.name, myDevice.name, str(match)))
                    myDevice.updateStateOnServer(key='onOffState', value = match)

    ########################################

    def getAllDevices(self, filter=None, valuesDict=None, typeId=0, targetId=0):

        retList = []
        for dev in indigo.devices.iter():
            retList.append((dev.id, dev.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def getStateList(self, filter, valuesDict, typeId, targetId):
        retList = []

        baseDeviceId = valuesDict.get("baseDevice", None)
        if not baseDeviceId:
            return retList

        baseDevice = indigo.devices[int(baseDeviceId)]

        for stateKey, stateValue in baseDevice.states.items():
            retList.append((stateKey, stateKey))
        retList.sort(key=lambda tup: tup[1])
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh

    def menuChanged(self, valuesDict, typeId, devId):
        return valuesDict
