#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
## Python to interface with MyQ garage doors.
## based on https://github.com/Einstein42/myq-garage

import os
import plistlib
import sys
import time
import logging
import xml.etree.ElementTree as ET

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
        indigo.devices.subscribeToChanges()

    def shutdown(self):
        indigo.server.log(u"Shutting down Masquerade")


    def deviceStartComm(self, device):

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        if instanceVers >= kCurDevVersCount:
            self.logger.debug(device.name + u": Device Version is up to date")
        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps

            newProps["devVersCount"] = kCurDevVersCount
            device.replacePluginPropsOnServer(newProps)
            device.stateListOrDisplayStateIdChanged()
            self.logger.debug(u"Updated " + device.name + " to version " + str(kCurDevVersCount))
        else:
            self.logger.error(u"Unknown device version: " + str(instanceVers) + " for device " + device.name)

        self.logger.debug("Adding Device %s (%d) to device list" % (device.name, device.id))
        assert device.id not in self.masqueradeList
        self.masqueradeList[device.id] = device
        baseDevice = indigo.devices[int(device.pluginProps["baseDevice"])]
        self.updateDevice(device, None, baseDevice)


    def deviceStopComm(self, device):
        self.logger.debug("Removing Device %s (%d) from device list" % (device.name, device.id))
        assert device.id in self.masqueradeList
        del self.masqueradeList[device.id]


    ########################################
    # Menu Methods
    ########################################



    ########################################
    # ConfigUI methods
    ########################################

    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorDict = indigo.Dict()

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

    ################################################################################
    #
    #   Scaling methods

    def scaleBaseToMasq(self, masqDevice, input):

        lowLimit = int(masqDevice.pluginProps["lowLimitState"])
        highLimit = int(masqDevice.pluginProps["highLimitState"])
        reverse = bool(masqDevice.pluginProps["reverseState"])

        if input < lowLimit:
            self.logger.warning(u"scaleBaseToMasq: Input value for %s is lower than expected: %d" % (masqDevice.name, input))
            input = lowLimit
        elif input > highLimit:
            self.logger.warning(u"scaleBaseToMasq: Input value for %s is higher than expected: %d" % (masqDevice.name, input))
            input = highLimit

        scaled = int((input - lowLimit) * (100.0 / (highLimit - lowLimit)))

        if reverse:
            scaled = 100 - scaled

        self.logger.debug(u"scaleBaseToMasq: lowLimit = %d, highLimit = %d, reverse = %s, input = %d, scaled = %d" % (lowLimit, highLimit, str(reverse), input, scaled))
        return scaled

    def scaleMasqToBase(self, masqDevice, input):

        lowLimit = int(masqDevice.pluginProps["lowLimitAction"])
        highLimit = int(masqDevice.pluginProps["highLimitAction"])
        reverse = bool(masqDevice.pluginProps["reverseAction"])
        valFormat = masqDevice.pluginProps["masqValueFormat"]

        scaled = int((input * (highLimit - lowLimit) / 100.0) + lowLimit)

        if reverse:
            scaled = highLimit - (scaled - lowLimit)

        if valFormat == "Decimal":
            scaledString = str(scaled)
        elif valFormat == "Hexidecimal":
            scaledString = '{:02x}'.format(scaled)
        elif valFormat == "Octal":
            scaledString = oct(scaled)
        else:
            self.logger.error(u"scaleBaseToMasq: Unknown masqValueFormat = %s" % (valFormat))

        self.logger.debug(u"scaleMasqToBase: lowLimit = %d, highLimit = %d, reverse = %s, input = %d, format = %s, scaled = %s" % (lowLimit, highLimit, str(reverse), input, valFormat, scaledString))
        return scaledString


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

        for masqDeviceId, masqDevice in sorted(self.masqueradeList.iteritems()):
            baseDevice = int(masqDevice.pluginProps["baseDevice"])
            if oldDevice.id == baseDevice:
                self.updateDevice(masqDevice, oldDevice, newDevice)


    def updateDevice(self, masqDevice, oldDevice, newDevice):
        if masqDevice.deviceTypeId == "masqSensor":
            masqState = masqDevice.pluginProps["masqState"]
            if oldDevice == None or oldDevice.states[masqState] != newDevice.states[masqState]:
                matchString = masqDevice.pluginProps["matchString"]
                reverse = bool(masqDevice.pluginProps["reverse"])
                match = (str(newDevice.states[masqState]) == matchString)
                if reverse:
                    match = not match
                self.logger.debug(u"updateDevice masqSensor:  %s (%s) --> %s (%s)" % (newDevice.name, newDevice.states[masqState], masqDevice.name, str(match)))

                if masqDevice.pluginProps["masqSensorSubtype"] == "Generic":
                    masqDevice.updateStateOnServer(key='onOffState', value = match)
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.None)

                elif masqDevice.pluginProps["masqSensorSubtype"] == "MotionSensor":
                    masqDevice.updateStateOnServer(key='onOffState', value = match)
                    if match:
                        masqDevice.updateStateImageOnServer(indigo.kStateImageSel.MotionSensorTripped)
                    else:
                        masqDevice.updateStateImageOnServer(indigo.kStateImageSel.MotionSensor)
                    
                elif masqDevice.pluginProps["masqSensorSubtype"] == "Power":
                    masqDevice.updateStateOnServer(key='onOffState', value = match)
                    if match:
                        masqDevice.updateStateImageOnServer(indigo.kStateImageSel.PowerOn)
                    else:
                        masqDevice.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)
                    
                else:
                    self.logger.debug(u"updateDevice masqSensor, unknown subtype: %s" % (masqDevice.pluginProps["masqSensorSubtype"]))

        elif masqDevice.deviceTypeId == "masqValueSensor":
            masqState = masqDevice.pluginProps["masqState"]
            if oldDevice == None or oldDevice.states[masqState] != newDevice.states[masqState]:
                baseValue = float(newDevice.states[masqState])
                self.logger.debug(u"updateDevice masqValueSensor: %s (%d) --> %s (%d)" % (newDevice.name, baseValue, masqDevice.name, baseValue))
                
                if masqDevice.pluginProps["masqSensorSubtype"] == "Generic":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.None)
                    masqDevice.updateStateOnServer(key='sensorValue', value = baseValue)

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Temperature-F":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.TemperatureSensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value = baseValue, decimalPlaces=1, uiValue=str(baseValue) + u' °F')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Temperature-C":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.TemperatureSensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value = baseValue, decimalPlaces=1, uiValue=str(baseValue) + u' °C')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Humidity":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.HumiditySensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value = baseValue, decimalPlaces=0, uiValue=str(baseValue) + u'%')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Luminence":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.LightSensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value = baseValue, decimalPlaces=0, uiValue=str(baseValue) + u' lux')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Luminence%":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.LightSensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value = baseValue, decimalPlaces=0, uiValue=str(baseValue) + u'%')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Energy":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.EnergyMeterOn)
                    masqDevice.updateStateOnServer(key='sensorValue', value = baseValue, decimalPlaces=0, uiValue=str(baseValue) + u' watts')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "ppm":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.None)
                    masqDevice.updateStateOnServer(key='sensorValue', value = baseValue, decimalPlaces=0, uiValue=str(baseValue) + u'ppm')

                else:
                    self.logger.debug(u"updateDevice masqSensor, unknown subtype: %s" % (masqDevice.pluginProps["masqSensorSubtype"]))
                    

        elif masqDevice.deviceTypeId == "masqDimmer":
            masqState = masqDevice.pluginProps["masqState"]
            if oldDevice == None or oldDevice.states[masqState] != newDevice.states[masqState]:
                baseValue = int(newDevice.states[masqState])
                scaledValue = self.scaleBaseToMasq(masqDevice, baseValue)
                self.logger.debug(u"updateDevice masqDimmer: %s (%d) --> %s (%d)" % (newDevice.name, baseValue, masqDevice.name, scaledValue))
                masqDevice.updateStateOnServer(key='brightnessLevel', value = scaledValue)

        elif masqDevice.deviceTypeId == "masqSpeedControl":
            if oldDevice == None or oldDevice.brightness != newDevice.brightness:
                baseValue = newDevice.brightness    # convert this to a speedIndex?
                self.logger.debug(u"updateDevice masqSpeedControl: %s (%d) --> %s (%d)" % (newDevice.name, baseValue, masqDevice.name, baseValue))
                masqDevice.updateStateOnServer(key='speedLevel', value = baseValue)

        elif masqDevice.deviceTypeId == "masqSprinkler":
            if oldDevice == None or oldDevice.onState != newDevice.onState:
                self.logger.debug(u"updateDevice masqSprinkler: {} ({}) --> {} ({})".format(newDevice.name, newDevice.onState, masqDevice.name, newDevice.onState))
                masqDevice.updateStateOnServer(key='activeZone', value = (1 if newDevice.onState else 0))



    ########################################

    def actionControlDevice(self, action, dev):

        if dev.pluginProps['masqAction']=="use Standard Indigo Commands":
            if action.deviceAction == indigo.kDeviceAction.TurnOn:
                self.logger.debug(u"actionControlDevice: \"%s\" Turn On" % dev.name)
                indigo.device.turnOn(int(dev.pluginProps["baseDevice"]))
            elif action.deviceAction == indigo.kDeviceAction.TurnOff:
                self.logger.debug(u"actionControlDevice: \"%s\" Turn Off" % dev.name)
                indigo.device.turnOff(int(dev.pluginProps["baseDevice"]))
            elif action.deviceAction == indigo.kDeviceAction.SetBrightness:
                self.logger.debug(u"actionControlDevice: \"%s\" Set Brightness to %d " % (dev.name, action.actionValue))
                if action.actionValue >0:
                    indigo.device.turnOn(int(dev.pluginProps["baseDevice"]))
                elif action.actionValue == 0:
                    indigo.device.turnOff(int(dev.pluginProps["baseDevice"]))
            return
        else:
            basePlugin = indigo.server.getPlugin(dev.pluginProps["devicePlugin"])
            if basePlugin.isEnabled():
                if action.deviceAction == indigo.kDeviceAction.TurnOn:
                    self.logger.debug(u"actionControlDevice: \"%s\" Turn On" % dev.name)
                    if dev.pluginProps["masqValueField"]:
                        props = { dev.pluginProps["masqValueField"] : dev.pluginProps["highLimitState"] }
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]),  props=props)
                    else:
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]) )

                elif action.deviceAction == indigo.kDeviceAction.TurnOff:
                    self.logger.debug(u"actionControlDevice: \"%s\" Turn Off" % dev.name)
                    if dev.pluginProps["masqValueField"]:
                        props = { dev.pluginProps["masqValueField"]: dev.pluginProps["lowLimitState"] }
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]),  props=props)
                    else:
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]))

                elif action.deviceAction == indigo.kDeviceAction.SetBrightness:
                    if dev.pluginProps["masqValueField"]:
                        scaledValueString = self.scaleMasqToBase(dev, action.actionValue)
                        self.logger.debug(u"actionControlDevice: \"%s\" Set Brightness to %d (scaled = %s)" % (dev.name, action.actionValue, scaledValueString))
                        props = { dev.pluginProps["masqValueField"] : scaledValueString }
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]),  props=props)

                else:
                    self.logger.error(u"actionControlDevice: \"%s\" Unsupported action requested: %s" % (dev.name, str(action)))

            else:
                self.logger.warning(u"actionControlDevice: Device %s is disabled." % (dev.name))


    def actionControlSpeedControl(self, action, dev):
        self.logger.debug(u"actionControlSpeedControl: \"%s\" Set Speed to %d" % (dev.name, action.actionValue))
        scaleFactor = int(dev.pluginProps["scaleFactor"])
        indigo.dimmer.setBrightness(int(dev.pluginProps["baseDevice"]), value=(action.actionValue * scaleFactor))


    def actionControlSprinkler(self, action, dev):
        if action.sprinklerAction == indigo.kSprinklerAction.ZoneOn:
            self.logger.debug(u"actionControlSprinkler: \"{}\" On".format(dev.name))
            indigo.device.turnOn(int(dev.pluginProps["baseDevice"]))
        elif action.sprinklerAction == indigo.kSprinklerAction.AllZonesOff:
            self.logger.debug(u"actionControlSprinkler: \"{}\" AllZonesOff".format(dev.name))
            indigo.device.turnOff(int(dev.pluginProps["baseDevice"]))
        


    ########################################################################
    # This method is called to generate a list of plugin identifiers / names
    ########################################################################
    def getPluginList(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
        pluginFolders =['Plugins', 'Plugins (Disabled)']
        for pluginFolder in pluginFolders:
            tempList = []
            pluginsList = os.listdir(indigoInstallPath + '/' + pluginFolder)
            for plugin in pluginsList:
                # Check for Indigo Plugins and exclude 'system' plugins
                if (plugin.lower().endswith('.indigoplugin')) and (not plugin[0:1] == '.'):
                    # retrieve plugin Info.plist file
                    path = indigoInstallPath + "/" + pluginFolder + "/" + plugin + "/Contents/Info.plist"
                    try:
                        pl = plistlib.readPlist(path)
                    except:
                        self.logger.warning(u"getPluginList: Unable to parse plist, skipping: %s" % (path))
                    else:
#                        self.logger.debug(u"getPluginList: reading plist: %s" % (path))
                        bundleId = pl["CFBundleIdentifier"]
                        if self.pluginId != bundleId:
                            # Don't include self (i.e. this plugin) in the plugin list
                            displayName = pl["CFBundleDisplayName"]
                            # if disabled plugins folder, append 'Disabled' to name
                            if pluginFolder == 'Plugins (Disabled)':
                                displayName += ' [Disabled]'
                            tempList.append((bundleId, displayName))
            tempList.sort(key=lambda tup: tup[1])
            retList = retList + tempList

        return retList

    def getDevices(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []

        deviceClass = valuesDict.get("deviceClass", "plugin")
        if deviceClass != "plugin":
            for dev in indigo.devices.iter(deviceClass):
                retList.append((dev.id, dev.name))
        else:
            devicePlugin = valuesDict.get("devicePlugin", None)
            for dev in indigo.devices.iter():
                if dev.protocol == indigo.kProtocol.Plugin and dev.pluginId == devicePlugin:
                    for pluginId, pluginDict in dev.globalProps.iteritems():
                        pass
                    retList.append((dev.id, dev.name))

        retList.sort(key=lambda tup: tup[1])
        return retList

    def getStateList(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        baseDeviceId = valuesDict.get("baseDevice", None)

        if not baseDeviceId:
            return retList
        
        try:
            baseDevice = indigo.devices[int(baseDeviceId)]
        except:
            return retList
        
        for stateKey, stateValue in baseDevice.states.items():
            retList.append((stateKey, stateKey))
        retList.sort(key=lambda tup: tup[1])

        return retList

    def getActionList(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = ["use Standard Indigo Commands"]
        indigoInstallPath = indigo.server.getInstallFolderPath()
        pluginsList = os.listdir(indigoInstallPath + '/Plugins')
        for plugin in pluginsList:
            if (plugin.lower().endswith('.indigoplugin')) and (not plugin[0:1] == '.'):
                path = indigoInstallPath + "/Plugins/" + plugin + "/Contents/Info.plist"
                try:
                    pl = plistlib.readPlist(path)
                except:
                    self.logger.warning(u"getActionList: Unable to parse plist, skipping: %s" % (path))
                else:
                    bundleId = pl["CFBundleIdentifier"]
                    if bundleId == valuesDict.get("devicePlugin", None):
                        self.logger.debug("getActionList, checking  bundleId = %s" % (bundleId))
                        tree = ET.parse(indigoInstallPath + "/Plugins/" + plugin + "/Contents/Server Plugin/Actions.xml")
                        actions = tree.getroot()
                        for action in actions:
                            if action.tag == "Action":
                                self.logger.debug("getActionList, Action attribs = %s" % (action.attrib))
                                name = action.find('Name')
                                callBack = action.find('CallbackMethod')
                                if name != None and callBack != None:
                                    self.logger.debug("getActionList, Action id = %s, name = '%s', callBackMethod = %s" % (action.attrib["id"], name.text, callBack.text))
                                    retList.append((action.attrib["id"], name.text))

        retList.sort(key=lambda tup: tup[1])
        return retList

    def getActionFieldList(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
        pluginsList = os.listdir(indigoInstallPath + '/Plugins')
        for plugin in pluginsList:
            if (plugin.lower().endswith('.indigoplugin')) and (not plugin[0:1] == '.'):
                path = indigoInstallPath + "/Plugins/" + plugin + "/Contents/Info.plist"
                try:
                    pl = plistlib.readPlist(path)
                except:
                    self.logger.warning(u"getActionFieldList: Unable to parse plist, skipping: %s" % (path))
                else:
                    bundleId = pl["CFBundleIdentifier"]
                    if bundleId == valuesDict.get("devicePlugin", None):
                        tree = ET.parse(indigoInstallPath + "/Plugins/" + plugin + "/Contents/Server Plugin/Actions.xml")
                        actions = tree.getroot()
                        if actions:
                            for action in actions:
                                if action.tag == "Action" and action.attrib["id"] == valuesDict.get("masqAction", None):
                                    configUI = action.find('ConfigUI')
                                    for field in configUI:
                                        self.logger.debug("ConfigUI List: child tag = %s, attrib = %s" % (field.tag, field.attrib))

                                        if not bool(field.attrib.get("hidden", None)):
                                            retList.append((field.attrib["id"], field.attrib["id"]))
                        
        retList.sort(key=lambda tup: tup[1])
        return retList


    # doesn't do anything, just needed to force other menus to dynamically refresh

    def menuChanged(self, valuesDict, typeId, devId):
        return valuesDict


    def getDeviceConfigUiValues(self, pluginProps, typeId, devId):
        self.logger.debug("getDeviceConfigUiValues, typeID = " + typeId)
        valuesDict = indigo.Dict(pluginProps)
        errorsDict = indigo.Dict()
        return (valuesDict, errorsDict)

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        self.logger.debug(u"validateDeviceConfigUi, typeID = " + typeId)
        errorsDict = indigo.Dict()
        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)
