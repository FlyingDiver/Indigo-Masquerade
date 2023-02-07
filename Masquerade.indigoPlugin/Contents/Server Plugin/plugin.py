#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import os
import plistlib
import sys
import time
import logging
import xml.etree.ElementTree as ET  # noqa

kCurDevVersCount = 0  # current version of plugin devices


################################################################################
class Plugin(indigo.PluginBase):

    ########################################
    # Main Plugin methods
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)
        self.logLevel = int(self.pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"logLevel = {str(self.logLevel)}")

        self.masqueradeList = {}

    def startup(self):
        self.logger.info("Starting Masquerade")
        indigo.devices.subscribeToChanges()

    def shutdown(self):
        self.logger.info("Shutting down Masquerade")

    def deviceStartComm(self, device):

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        if instanceVers >= kCurDevVersCount:
            self.logger.debug(f"{device.name}: Device Version is up to date")
        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps

            newProps["devVersCount"] = kCurDevVersCount
            device.replacePluginPropsOnServer(newProps)
            device.stateListOrDisplayStateIdChanged()
            self.logger.debug(f"Updated {device.name} to version {kCurDevVersCount}")
        else:
            self.logger.error(f"Unknown device version: {instanceVers} for device {device.name}")

        self.logger.debug(f"Adding Device {device.name} ({device.id}) to device list")
        assert device.id not in self.masqueradeList
        self.masqueradeList[device.id] = device
        baseDevice = indigo.devices[int(device.pluginProps["baseDevice"])]
        self.updateDevice(device, None, baseDevice)

    def deviceStopComm(self, device):
        self.logger.debug(f"Removing Device {device.name} ({device.id}) from device list")
        assert device.id in self.masqueradeList
        del self.masqueradeList[device.id]

    ########################################
    # ConfigUI methods
    ########################################

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(self.pluginPrefs.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")

    ################################################################################
    #   Scaling methods
    ################################################################################

    def scaleBaseToMasq(self, masqDevice, val):
        lowLimit = int(masqDevice.pluginProps["lowLimitState"])
        highLimit = int(masqDevice.pluginProps["highLimitState"])
        reverse = bool(masqDevice.pluginProps["reverseState"])

        if val < lowLimit:
            self.logger.warning(f"scaleBaseToMasq: Input value for {masqDevice.name} is lower than expected: {val}")
            val = lowLimit
        elif val > highLimit:
            self.logger.warning(f"scaleBaseToMasq: Input value for {masqDevice.name} is higher than expected: {val}")
            val = highLimit

        scaled = int((val - lowLimit) * (100.0 / (highLimit - lowLimit)))

        if reverse:
            scaled = 100 - scaled

        self.logger.debug(
            f"scaleBaseToMasq: lowLimit = {lowLimit}, highLimit = {highLimit}, reverse = {str(reverse)}, input = {val}, scaled = {scaled}")
        return scaled

    def scaleMasqToBase(self, masqDevice, val):
        lowLimit = int(masqDevice.pluginProps["lowLimitAction"])
        highLimit = int(masqDevice.pluginProps["highLimitAction"])
        reverse = bool(masqDevice.pluginProps["reverseAction"])
        valFormat = masqDevice.pluginProps["masqValueFormat"]

        scaled = int((val * (highLimit - lowLimit) / 100.0) + lowLimit)

        if reverse:
            scaled = highLimit - (scaled - lowLimit)

        if valFormat == "Decimal":
            scaledString = str(scaled)
        elif valFormat == "Hexadecimal":
            scaledString = '{:02x}'.format(scaled)
        elif valFormat == "Octal":
            scaledString = oct(scaled)
        else:
            self.logger.error(f"scaleMasqToBase: Unknown masqValueFormat = {valFormat}")
            return None

        self.logger.debug(
            f"scaleMasqToBase: lowLimit = {lowLimit}, highLimit = {highLimit}, reverse = {str(reverse)}, input = {val}, format = {valFormat}, scaled = {scaledString}")
        return scaledString

    ###############################################################################
    # delegate methods for indigo.devices.subscribeToChanges()
    ###############################################################################

    def deviceDeleted(self, delDevice):
        indigo.PluginBase.deviceDeleted(self, delDevice)

        for myDeviceId, myDevice in sorted(self.masqueradeList.items()):
            baseDevice = int(myDevice.pluginProps["baseDevice"])
            if delDevice.id == baseDevice:
                self.logger.info(f"A device ({delDevice.name}) that was being Masqueraded has been deleted.  Disabling {myDevice.name}")
                indigo.device.enable(myDevice, value=False)  # disable it

    def deviceUpdated(self, oldDevice, newDevice):
        indigo.PluginBase.deviceUpdated(self, oldDevice, newDevice)

        for masqDeviceId, masqDevice in sorted(self.masqueradeList.items()):
            baseDevice = int(masqDevice.pluginProps["baseDevice"])
            if oldDevice.id == baseDevice:
                self.updateDevice(masqDevice, oldDevice, newDevice)

    ###############################################################################

    def updateDevice(self, masqDevice, oldDevice, newDevice):
        if masqDevice.deviceTypeId == "masqSensor":
            masqState = masqDevice.pluginProps["masqState"]
            if oldDevice is None or oldDevice.states[masqState] != newDevice.states[masqState]:
                matchString = masqDevice.pluginProps["matchString"]
                reverse = bool(masqDevice.pluginProps["reverse"])
                match = (str(newDevice.states[masqState]) == matchString)
                if reverse:
                    match = not match
                self.logger.debug(f"updateDevice masqSensor: {newDevice.name} ({newDevice.states[masqState]}) -> {masqDevice.name} ({match})")

                if masqDevice.pluginProps["masqSensorSubtype"] == "Generic":
                    masqDevice.updateStateOnServer(key='onOffState', value=match)
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.NoImage)

                elif masqDevice.pluginProps["masqSensorSubtype"] == "MotionSensor":
                    masqDevice.updateStateOnServer(key='onOffState', value=match)
                    if match:
                        masqDevice.updateStateImageOnServer(indigo.kStateImageSel.MotionSensorTripped)
                    else:
                        masqDevice.updateStateImageOnServer(indigo.kStateImageSel.MotionSensor)

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Power":
                    masqDevice.updateStateOnServer(key='onOffState', value=match)
                    if match:
                        masqDevice.updateStateImageOnServer(indigo.kStateImageSel.PowerOn)
                    else:
                        masqDevice.updateStateImageOnServer(indigo.kStateImageSel.PowerOff)

                else:
                    self.logger.debug(f"updateDevice masqSensor, unknown subtype: {masqDevice.pluginProps['masqSensorSubtype']}")

        elif masqDevice.deviceTypeId == "masqValueSensor":
            masqState = masqDevice.pluginProps["masqState"]
            if oldDevice is None or oldDevice.states[masqState] != newDevice.states[masqState]:
                try:
                    baseValue = float(newDevice.states[masqState])
                except ValueError:
                    self.logger.debug(f"{masqDevice.name}: Unable to convert state {masqState} = {newDevice.states[masqState]} to float")
                    baseValue = 0
                self.logger.debug(f"updateDevice masqValueSensor: {newDevice.name} ({baseValue}) -> {masqDevice.name} ({baseValue})")

                if masqDevice.pluginProps["masqSensorSubtype"] == "Generic":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.NoImage)
                    masqDevice.updateStateOnServer(key='sensorValue', value=baseValue)

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Temperature-F":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.TemperatureSensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value=baseValue, decimalPlaces=1, uiValue=str(baseValue) + u' °F')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Temperature-C":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.TemperatureSensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value=baseValue, decimalPlaces=1, uiValue=str(baseValue) + u' °C')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Humidity":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.HumiditySensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value=baseValue, decimalPlaces=0, uiValue=str(baseValue) + u'%')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Luminance":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.LightSensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value=baseValue, decimalPlaces=0, uiValue=str(baseValue) + u' lux')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Luminance%":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.LightSensor)
                    masqDevice.updateStateOnServer(key='sensorValue', value=baseValue, decimalPlaces=0, uiValue=str(baseValue) + u'%')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "Energy":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.EnergyMeterOn)
                    masqDevice.updateStateOnServer(key='sensorValue', value=baseValue, decimalPlaces=0, uiValue=str(baseValue) + u' watts')

                elif masqDevice.pluginProps["masqSensorSubtype"] == "ppm":
                    masqDevice.updateStateImageOnServer(indigo.kStateImageSel.NoImage)
                    masqDevice.updateStateOnServer(key='sensorValue', value=baseValue, decimalPlaces=0, uiValue=str(baseValue) + u'ppm')

                else:
                    self.logger.debug(f"updateDevice masqSensor, unknown subtype: {masqDevice.pluginProps['masqSensorSubtype']}")

        elif masqDevice.deviceTypeId == "masqDimmer":
            masqState = masqDevice.pluginProps["masqState"]
            if oldDevice is None or oldDevice.states[masqState] != newDevice.states[masqState]:
                baseValue = int(newDevice.states[masqState])
                scaledValue = self.scaleBaseToMasq(masqDevice, baseValue)
                self.logger.debug(f"updateDevice masqDimmer: {newDevice.name} ({baseValue}) -> {masqDevice.name} ({scaledValue})")
                masqDevice.updateStateOnServer(key='brightnessLevel', value=scaledValue)

        elif masqDevice.deviceTypeId == "masqSpeedControl":
            if oldDevice is None or oldDevice.brightness != newDevice.brightness:
                baseValue = newDevice.brightness  # convert this to a speedIndex?
                self.logger.debug(f"updateDevice masqSpeedControl: {newDevice.name} ({baseValue}) --> {masqDevice.name} ({baseValue})")
                masqDevice.updateStateOnServer(key='speedLevel', value=baseValue)

        elif masqDevice.deviceTypeId == "masqSprinkler":
            if oldDevice is None or oldDevice.onState != newDevice.onState:
                self.logger.debug(
                    f"updateDevice masqSprinkler: {newDevice.name} ({newDevice.onState}) --> {masqDevice.name} ({newDevice.onState})")
                masqDevice.updateStateOnServer(key='activeZone', value=(1 if newDevice.onState else 0))

    ########################################

    def actionControlDevice(self, action, dev):

        if dev.pluginProps['masqAction'] == "---":
            if action.deviceAction == indigo.kDeviceAction.TurnOn:
                self.logger.debug(f"{dev.name}: actionControlDevice: Turn On")
                indigo.device.turnOn(int(dev.pluginProps["baseDevice"]))

            elif action.deviceAction == indigo.kDeviceAction.TurnOff:
                self.logger.debug(f"{dev.name}: actionControlDevice: Turn Off")
                indigo.device.turnOff(int(dev.pluginProps["baseDevice"]))
            elif action.deviceAction == indigo.kDeviceAction.SetBrightness:

                self.logger.debug(f"{dev.name}: actionControlDevice: Set Brightness to {action.actionValue}")
                if action.actionValue > 0:
                    indigo.device.turnOn(int(dev.pluginProps["baseDevice"]))
                else:
                    indigo.device.turnOff(int(dev.pluginProps["baseDevice"]))

            else:
                self.logger.error(f"{dev.name}: actionControlDevice: Unsupported action requested: {str(action)}")

        else:
            basePlugin = indigo.server.getPlugin(dev.pluginProps["devicePlugin"])
            if basePlugin.isEnabled():
                if action.deviceAction == indigo.kDeviceAction.TurnOn:
                    self.logger.debug(f"{dev.name}: actionControlDevice: Turn On")
                    if dev.pluginProps["masqValueField"]:
                        props = {dev.pluginProps["masqValueField"]: dev.pluginProps["highLimitState"]}
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]), props=props)
                    else:
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]))

                elif action.deviceAction == indigo.kDeviceAction.TurnOff:
                    self.logger.debug(f"{dev.name}: actionControlDevice: Turn Off")
                    if dev.pluginProps["masqValueField"]:
                        props = {dev.pluginProps["masqValueField"]: dev.pluginProps["lowLimitState"]}
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]), props=props)
                    else:
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]))

                elif action.deviceAction == indigo.kDeviceAction.SetBrightness:
                    if dev.pluginProps["masqValueField"]:
                        scaledValueString = self.scaleMasqToBase(dev, action.actionValue)
                        self.logger.debug(f"{dev.name}: actionControlDevice: Set Brightness to {action.actionValue} ({scaledValueString} scaled)")
                        props = {dev.pluginProps["masqValueField"]: scaledValueString}
                        basePlugin.executeAction(dev.pluginProps["masqAction"], deviceId=int(dev.pluginProps["baseDevice"]), props=props)

                else:
                    self.logger.error(f"{dev.name}: actionControlDevice: Unsupported action requested: {str(action)}")
            else:
                self.logger.warning(f"actionControlDevice: Plugin for device {dev.name} is disabled.")

    def actionControlSpeedControl(self, action, dev):
        self.logger.debug(f"actionControlSpeedControl: '{dev.name}' Set Speed to {action.actionValue}")
        scaleFactor = int(dev.pluginProps["scaleFactor"])
        indigo.dimmer.setBrightness(int(dev.pluginProps["baseDevice"]), value=(action.actionValue * scaleFactor))

    def actionControlSprinkler(self, action, dev):
        if action.sprinklerAction == indigo.kSprinklerAction.ZoneOn:
            self.logger.debug(f"actionControlSprinkler: '{dev.name}' On")
            indigo.device.turnOn(int(dev.pluginProps["baseDevice"]))
        elif action.sprinklerAction == indigo.kSprinklerAction.AllZonesOff:
            self.logger.debug(f"actionControlSprinkler: '{dev.name}' AllZonesOff")
            indigo.device.turnOff(int(dev.pluginProps["baseDevice"]))

    ########################################################################
    # This method is called to generate a list of plugin identifiers / names
    ########################################################################
    def getPluginList(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
        pluginFolders = ['Plugins', 'Plugins (Disabled)']
        for pluginFolder in pluginFolders:
            tempList = []
            pluginsList = os.listdir(f"{indigoInstallPath}/{pluginFolder}")
            for plugin in pluginsList:
                # Check for Indigo Plugins and exclude 'system' plugins
                if (plugin.lower().endswith('.indigoplugin')) and (not plugin[0:1] == '.'):
                    # retrieve plugin Info.plist file
                    path = f"{indigoInstallPath}/{pluginFolder}/{plugin}/Contents/Info.plist"
                    with open(path, "rb") as fp:
                        try:
                            pl = plistlib.load(fp)
                        except Exception as err:
                            self.logger.warning(f"getPluginList: Unable to parse plist, skipping: {path}, err = {err}")
                        else:
                            self.logger.threaddebug(f"getPluginList: pl = {pl}")
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

    @staticmethod
    def getDevices(filter="", valuesDict=None, typeId="", targetId=0):
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

    @staticmethod
    def getStateList(filter="", valuesDict=None, typeId="", targetId=0):
        retList = []
        baseDeviceId = valuesDict.get("baseDevice", None)
        if not baseDeviceId:
            return retList
        try:
            baseDevice = indigo.devices[int(baseDeviceId)]
        except (Exception,):
            return retList
        for stateKey, stateValue in baseDevice.states.items():
            retList.append((stateKey, stateKey))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def getActionList(self, filter="", valuesDict=None, typeId="", targetId=0):
        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
        pluginsList = os.listdir(indigoInstallPath + '/Plugins')
        for plugin in pluginsList:
            if (plugin.lower().endswith('.indigoplugin')) and (not plugin[0:1] == '.'):
                path = f"{indigoInstallPath}/Plugins/{plugin}/Contents/Info.plist"
                with open(path, "rb") as fp:
                    try:
                        pl = plistlib.load(fp)
                    except Exception as err:
                        self.logger.warning(f"getPluginList: Unable to parse plist, skipping: {path}, err = {err}")
                    else:
                        bundleId = pl["CFBundleIdentifier"]
                        if bundleId == valuesDict.get("devicePlugin", None):
                            self.logger.debug(f"getActionList, checking  bundleId = {bundleId}")
                            tree = ET.parse(f"{indigoInstallPath}/Plugins/{plugin}/Contents/Server Plugin/Actions.xml")
                            actions = tree.getroot()
                            for action in actions:
                                if action.tag == "Action":
                                    self.logger.debug(f"getActionList, Action attribs = {action.attrib}")
                                    name = action.find('Name')
                                    callBack = action.find('CallbackMethod')
                                    if name is not None and callBack is not None:
                                        self.logger.debug(f"getActionList, Action id = {action.attrib['id']}, name = '{name.text}', callBackMethod = {callBack.text}")
                                        retList.append((action.attrib["id"], name.text))

        retList.sort(key=lambda tup: tup[1])
        retList.insert(0, ("---", "Standard Commands (On, Off, Brightness)"))
        return retList

    def getActionFieldList(self, filter="", valuesDict=None, typeId="", targetId=0):

        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
        pluginsList = os.listdir(indigoInstallPath + '/Plugins')
        for plugin in pluginsList:
            if (plugin.lower().endswith('.indigoplugin')) and (not plugin[0:1] == '.'):
                path = f"{indigoInstallPath}/Plugins/{plugin}/Contents/Info.plist"
                with open(path, "rb") as fp:
                    try:
                        pl = plistlib.load(fp)
                    except Exception as err:
                        self.logger.warning(f"getPluginList: Unable to parse plist, skipping: {path}, err = {err}")
                    else:
                        bundleId = pl["CFBundleIdentifier"]
                        if bundleId == valuesDict.get("devicePlugin", None):
                            tree = ET.parse(f"{indigoInstallPath}/Plugins/{plugin}/Contents/Server Plugin/Actions.xml")
                            actions = tree.getroot()
                            if actions:
                                for action in actions:
                                    if action.tag == "Action" and action.attrib["id"] == valuesDict.get("masqAction", None):
                                        configUI = action.find('ConfigUI')
                                        for field in configUI:
                                            self.logger.debug(f"ConfigUI List: child tag = {field.tag}, attrib = {field.attrib}")
                                            if not bool(field.attrib.get("hidden", None)):
                                                retList.append((field.attrib["id"], field.attrib["id"]))

        retList.sort(key=lambda tup: tup[1])
        if len(retList) == 0:
            retList.insert(0, ("---", "None"))
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh
    @staticmethod
    def menuChanged(valuesDict, typeId, devId):
        return valuesDict
