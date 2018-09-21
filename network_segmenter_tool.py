# -*- coding: utf-8 -*-
"""
/***************************************************************************
 NetworkSegmenter
                                 A QGIS plugin
 This plugin clean a road centre line map.
                              -------------------
        begin                : 2016-11-10
        git sha              : $Format:%H$
        copyright            : (C) 2018 by Space SyntaxLtd
        email                : i.kolovou@spacesyntax.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import datetime

from PyQt4.QtCore import QThread, QSettings, QObject, pyqtSignal, QVariant
from qgis.core import *
from qgis.gui import *
from qgis.utils import *
import time

from network_segmenter_dialog import NetworkSegmenterDialog
from segment_tools import *  # better give these a name to make it explicit to which module the methods belong
from utilityFunctions import *

# Import the debug library - required for the cleaning class in separate thread
# set is_debug to False in release version
is_debug = False
try:
    import pydevd
    has_pydevd = True
except ImportError, e:
    has_pydevd = False
    is_debug = False

class NetworkSegmenterTool(QObject):

    # initialise class with self and iface
    def __init__(self, iface):
        QObject.__init__(self)

        self.iface=iface
        self.legend = self.iface.legendInterface()

        # load the dialog from the run method otherwise the objects gets created multiple times
        self.dlg = None

        # some globals
        self.segmenting = None
        self.thread = None

    def loadGUI(self):
        # create the dialog objects
        self.dlg = NetworkSegmenterDialog(self.getQGISDbs())

        # setup GUI signals
        self.dlg.closingPlugin.connect(self.unloadGUI)
        self.dlg.runButton.clicked.connect(self.startWorker)
        self.dlg.cancelButton.clicked.connect(self.killWorker)

        # add layers to dialog
        self.updateLayers()
        self.updateUnlinksLayers()

        # setup legend interface signals
        self.legend.itemAdded.connect(self.updateLayers)
        self.legend.itemRemoved.connect(self.updateLayers)
        self.legend.itemAdded.connect(self.updateUnlinksLayers)
        self.legend.itemRemoved.connect(self.updateUnlinksLayers)

        self.settings = None

        print 'settings',  self.settings

        # show the dialog
        self.dlg.show()
        # Run the dialog event loop
        result = self.dlg.exec_()

    def unloadGUI(self):
        if self.dlg:
            self.dlg.closingPlugin.disconnect(self.unloadGUI)
            self.dlg.runButton.clicked.disconnect(self.startWorker)
            self.dlg.cancelButton.clicked.disconnect(self.killWorker)
            self.settings = None
        try:
            self.legend.itemAdded.disconnect(self.updateLayers)
            self.legend.itemRemoved.disconnect(self.updateLayers)
            self.legend.itemAdded.disconnect(self.updateUnlinksLayers)
            self.legend.itemRemoved.disconnect(self.updateUnlinksLayers)
        except TypeError:
            pass

        self.dlg = None

    def getQGISDbs(self):
        """Return all PostGIS connection settings stored in QGIS
        :return: connection dict() with name and other settings
        """
        con_settings = []
        settings = QSettings()
        settings.beginGroup('/PostgreSQL/connections')
        for item in settings.childGroups():
            con = dict()
            con['name'] = unicode(item)
            con['host'] = unicode(settings.value(u'%s/host' % unicode(item)))
            con['port'] = unicode(settings.value(u'%s/port' % unicode(item)))
            con['database'] = unicode(settings.value(u'%s/database' % unicode(item)))
            con['username'] = unicode(settings.value(u'%s/username' % unicode(item)))
            con['password'] = unicode(settings.value(u'%s/password' % unicode(item)))
            con_settings.append(con)
        settings.endGroup()
        dbs = {}
        if len(con_settings) > 0:
            for conn in con_settings:
                dbs[conn['name']]= conn
        return dbs

    def getActiveLayers(self):
        layers_list = []
        for layer in self.iface.legendInterface().layers():
            if layer.isValid() and layer.type() == QgsMapLayer.VectorLayer:
                if layer.hasGeometryType() and (layer.geometryType() == 1):
                    layers_list.append(layer.name())
        return layers_list

    def updateLayers(self):
        layers = self.getActiveLayers()
        self.dlg.popActiveLayers(layers)

    def getpntplgLayers(self):
        layers_list = []
        for layer in self.iface.legendInterface().layers():
            if layer.isValid() and layer.type() == QgsMapLayer.VectorLayer:
                if layer.hasGeometryType() and (layer.geometryType() in [0, 2]):
                    layers_list.append(layer.name())
        return layers_list

    def updateUnlinksLayers(self):
        layers = self.getpntplgLayers()
        self.dlg.popUnlinksLayers(layers)

    def giveMessage(self, message, level):
        # Gives warning according to message
        self.iface.messageBar().pushMessage("Network segmenter: ", "%s" % (message), level, duration=5)

    def workerError(self, e, exception_string):
        # Gives error according to message
        QgsMessageLog.logMessage('Segmenting thread raised an exception: %s' % exception_string, level=QgsMessageLog.CRITICAL)
        self.dlg.close()

    def startWorker(self):
        print 'before started'
        self.dlg.segmentingProgress.reset()
        self.settings = self.dlg.get_settings()
        print 'settings', self.settings
        if self.settings['output_type'] == 'postgis':
            db_settings = self.dlg.get_dbsettings()
            self.settings.update(db_settings)

        if self.settings['input']:
            segmenting = self.Worker(self.settings , self.iface)
            # start the segmenting in a new thread
            thread = QThread()
            segmenting.moveToThread(thread)
            segmenting.finished.connect(self.workerFinished)
            segmenting.error.connect(self.workerError)
            segmenting.warning.connect(self.giveMessage)
            segmenting.segm_progress.connect(self.dlg.segmentingProgress.setValue)

            thread.started.connect(segmenting.run)

            thread.start()

            self.thread = thread
            self.segmenting = segmenting

            #if is_debug:
            print 'has started'
        else:
            self.giveMessage('Missing user input!', QgsMessageBar.INFO)
            return

    def workerFinished(self, ret):
        #if is_debug:
        print 'trying to finish'
        # get segmenting settings
        layer_name = self.settings['input']
        path = self.settings['output']
        output_type = self.settings['output_type']
        #  get settings from layer
        layer = getLayerByName(layer_name)
        crs = layer.dataProvider().crs()
        encoding = layer.dataProvider().encoding()
        geom_type = layer.dataProvider().geometryType()
        # create the segmenting results layers

        #try:

            # create clean layer
            #segmented = to_layer(ret[0], crs, encoding, geom_type, output_type, path, layer_name + '_segmented')
            #if segmented:
            #    QgsMapLayerRegistry.instance().addMapLayer(segmented)
            #    segmented.updateExtents()
            # create unlinks layer
            #if self.settings['errors']:

                #if break_Points:
                #    QgsMapLayerRegistry.instance().addMapLayer(break_Points)
                #    break_Points.updateExtents()

            #self.iface.mapCanvas().refresh()

            #self.giveMessage('Process ended successfully!', QgsMessageBar.INFO)

        #except Exception, e:
            # notify the user that sth went wrong
        #    self.segmenting.error.emit(e, traceback.format_exc())
        #    self.giveMessage('Something went wrong! See the message log for more information', QgsMessageBar.CRITICAL)

        # clean up the worker and thread
        self.segmenting.finished.disconnect(self.workerFinished)
        self.segmenting.error.disconnect(self.workerError)
        self.segmenting.warning.disconnect(self.giveMessage)
        self.segmenting.segm_progress.disconnect(self.dlg.segmentingProgress.setValue)

        self.thread.deleteLater()
        self.thread.quit()
        self.thread.wait()
        self.thread.deleteLater()

        if ret is not None:
            self.iface.messageBar().pushMessage(
                'The total area of name is area.')

        if is_debug: print 'thread running ', self.thread.isRunning()
        if is_debug: print 'has finished ', self.thread.isFinished()

        self.thread = None
        self.segmenting = None

        if self.dlg:
            self.dlg.segmentingProgress.reset()
            self.dlg.close()

    def killWorker(self):
        #if is_debug:
        print 'trying to cancel'
        # add emit signal to segmenttool or mergeTool only to stop the loop
        if self.segmenting:
            #try:
            #    dummy = self.segmenting.explodedGraph
            #    del dummy
            self.segmenting.killed = True
            try:
                self.segmenting.my_segmentor.kill()
            except e:
                pass
            #except AttributeError:
            #    pass
            # Disconnect signals
            self.segmenting.finished.disconnect(self.workerFinished)
            self.segmenting.error.disconnect(self.workerError)
            self.segmenting.warning.disconnect(self.giveMessage)
            self.segmenting.segm_progress.disconnect(self.dlg.segmentingProgress.setValue)
            ## self.segmenting.my_segmentor.progress.disconnect
            # Clean up thread and analysis
            self.segmenting.kill()
            self.segmenting.deleteLater()
            self.thread.quit()
            self.thread.wait()
            self.thread.deleteLater()
            self.segmenting = None
            self.dlg.segmentingProgress.reset()
            self.dlg.close()
        else:
            self.dlg.close()

    class Worker(QObject):

        # Setup signals
        finished = pyqtSignal(object)
        error = pyqtSignal(Exception, basestring)
        segm_progress = pyqtSignal(float)
        warning = pyqtSignal(str)
        segm_killed = pyqtSignal(bool)

        def __init__(self, settings, iface):
            QObject.__init__(self)
            self.settings = settings
            self.segm_killed = False
            self.iface = iface
            self.totalpr = 0
            self.my_segmentor = None
            # print ' class initiated'

        def add_step(self,step):
            self.totalpr += step
            return self.totalpr

        def run(self):
            if has_pydevd and is_debug:
                pydevd.settrace('localhost', port=53100, stdoutToServer=True, stderrToServer=True, suspend=False)
            ret = None
            if self.settings:
                # segmenting settings
                layer_name = self.settings['input']
                unlinks_layer_name = self.settings['unlinks']
                layer = getLayerByName(layer_name)
                unlinks = getLayerByName(unlinks_layer_name)
                stub_ratio = self.settings['stub_ratio']
                buffer = self.settings['buffer']
                errors = self.settings['errors']

                # print layer, unlinks, stub_ratio, buffer
                self.segm_progress.emit(5)
                self.my_segmentor = segmentor(layer, unlinks, stub_ratio, buffer, errors)

                # if self.my_segmentor.killed is True: return

                # self.my_segmentor.progress.connect(lambda incr=self.add_step(self.my_segmentor.step*80): self.segm_progress.emit(incr))

                ret = self.my_segmentor.segment()
                #self.my_segmentor.progress.disconnect()

                #print "survived!"

                self.segm_progress.emit(95)

            self.finished.emit(ret)

        def kill(self):
            print 'killed'
            self.segm_killed = True
