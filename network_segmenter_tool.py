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
from PyQt4.QtCore import Qt, QThread, QSettings

from qgis.core import *
from qgis.gui import *
from qgis.utils import *

#import db_manager.db_plugins.postgis.connector as con
import traceback

# Initialize Qt resources from file resources.py
import resources
# the dialog modules
from network_segmenter_dialog import NetworkSegmenterDialog

# additional modules
from sGraph.segment_tools import *  # better give these a name to make it explicit to which module the methods belong
from sGraph.utilityFunctions import *

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
        self.dlg.runButton.clicked.connect(self.startSegmenting)
        self.dlg.cancelButton.clicked.connect(self.killSegmenting)

        # add layers to dialog
        self.updateLayers()
        self.updateUnlinksLayers()

        # setup legend interface signals
        self.legend.itemAdded.connect(self.updateLayers)
        self.legend.itemRemoved.connect(self.updateLayers)
        self.legend.itemAdded.connect(self.updateUnlinksLayers)
        self.legend.itemRemoved.connect(self.updateUnlinksLayers)

        self.settings = None

        print 'set',  self.settings

        # show the dialog
        self.dlg.show()
        # Run the dialog event loop
        result = self.dlg.exec_()

    def unloadGUI(self):
        if self.dlg:
            self.dlg.closingPlugin.disconnect(self.unloadGUI)
            self.dlg.runButton.clicked.disconnect(self.startSegmenting)
            self.dlg.cancelButton.clicked.disconnect(self.killSegmenting)
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

    # SOURCE: Network Segmenter https://github.com/OpenDigitalWorks/NetworkSegmenter
    # SOURCE: https://snorfalorpagus.net/blog/2013/12/07/multithreading-in-qgis-python-plugins/

    def giveMessage(self, message, level):
        # Gives warning according to message
        self.iface.messageBar().pushMessage("Network segmenter: ", "%s" % (message), level, duration=5)

    def segmentingError(self, e, exception_string):
        # Gives error according to message
        QgsMessageLog.logMessage('Segmenting thread raised an exception: %s' % exception_string, level=QgsMessageLog.CRITICAL)
        self.dlg.close()

    def startSegmenting(self):
        print 'started'
        self.dlg.segmentingProgress.reset()
        self.settings = self.dlg.get_settings()
        print 'set', self.settings
        if self.settings['output_type'] == 'postgis':
            db_settings = self.dlg.get_dbsettings()
            self.settings.update(db_settings)

        if self.settings['input']:

            segmenting = self.segment(self.settings, self.iface)
            # start the segmenting in a new thread
            thread = QThread()
            segmenting.moveToThread(thread)
            segmenting.finished.connect(self.segmentingFinished)
            segmenting.error.connect(self.segmentingError)
            segmenting.warning.connect(self.giveMessage)
            segmenting.segm_progress.connect(self.dlg.segmentingProgress.setValue)

            thread.started.connect(segmenting.run)

            self.thread = thread
            self.segmenting = segmenting

            self.thread.start()

            if is_debug: print 'started'
        else:
            self.giveMessage('Missing user input!', QgsMessageBar.INFO)
            return

    def segmentingFinished(self, ret):
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
        try:
            # create clean layer
            if output_type == 'shp':
                final = to_shp(path, ret[0][0], ret[0][1], crs, 'segmented', encoding, geom_type)
            elif output_type == 'memory':
                final = to_shp(None, ret[0][0], ret[0][1], crs, path, encoding, geom_type)
            else:
                final = to_dblayer(self.settings['dbname'], self.settings['user'], self.settings['host'],
                                   self.settings['port'], self.settings['password'], self.settings['schema'],
                                   self.settings['table_name'], ret[0][1], ret[0][0], crs)
            if final:
                QgsMapLayerRegistry.instance().addMapLayer(final)
                final.updateExtents()
            # create unlinks layer
            if self.settings['breakages']:
                breakages = to_shp(None, ret[2][0], ret[2][1], crs, 'unlinks', encoding, 0)
                if breakages:
                    QgsMapLayerRegistry.instance().addMapLayer(breakages)
                    breakages.updateExtents()

            self.iface.mapCanvas().refresh()

            self.giveMessage('Process ended successfully!', QgsMessageBar.INFO)

        except Exception, e:
            # notify the user that sth went wrong
            self.segmenting.error.emit(e, traceback.format_exc())
            self.giveMessage('Something went wrong! See the message log for more information', QgsMessageBar.CRITICAL)

        # clean up the worker and thread
        self.thread.quit()
        self.thread.wait()
        self.thread.deleteLater()

        if is_debug: print 'thread running ', self.thread.isRunning()
        if is_debug: print 'has finished ', self.thread.isFinished()

        self.thread = None
        self.segmenting = None

        if self.dlg:
            self.dlg.segmentingProgress.reset()
            self.dlg.close()

    def killSegmenting(self):
        if is_debug: print 'trying to cancel'
        # add emit signal to segmenttool or mergeTool only to stop the loop
        if self.segmenting:

            try:
                dummy = self.segmenting.br
                del dummy
                self.segmenting.br.killed = True
            except AttributeError:
                pass
            try:
                dummy = self.segmenting.mrg
                del dummy
                self.segmenting.mrg.killed = True
            except AttributeError:
                pass
            # Disconnect signals
            self.segmenting.finished.disconnect(self.segmentingFinished)
            self.segmenting.error.disconnect(self.segmentingError)
            self.segmenting.warning.disconnect(self.giveMessage)
            self.segmenting.segm_progress.disconnect(self.dlg.segmentingProgress.setValue)
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


    # SOURCE: https://snorfalorpagus.net/blog/2013/12/07/multithreading-in-qgis-python-plugins/
    class segment(QObject):

        # Setup signals
        finished = pyqtSignal(object)
        error = pyqtSignal(Exception, basestring)
        segm_progress = pyqtSignal(float)
        warning = pyqtSignal(str)
        segm_killed = pyqtSignal(bool)

        def __init__(self, settings, iface):
            QObject.__init__(self)
            self.settings = settings
            self.iface = iface
            self.total =0

        def add_step(self,step):
            self.total += step
            return self.total

        def run(self):
            if has_pydevd and is_debug:
                pydevd.settrace('localhost', port=53100, stdoutToServer=True, stderrToServer=True, suspend=False)
            ret = None
            if self.settings:
                try:
                    # segmenting settings
                    layer_name = self.settings['input']
                    unlinks_layer_name = self.settings['unlinks']
                    # project settings
                    layer = getLayerByName(layer_name)
                    if unlinks_layer_name:
                        unlinks_layer = getLayerByName(unlinks_layer_name)

                    flds = getQFields(layer)
                    explodedGraph = segmentTool(flds)

                    if unlinks_layer_name:
                        explodedGraph.prepare_unlinks(unlinks_layer, 0) #todo buffer_threshold

                    if self.segm_killed is True or explodedGraph.killed is True: return

                    step = 30 / self.layer.featureCount()
                    explodedGraph.progress.connect(lambda incr=self.add_step(step): self.segm_progress.emit(incr))

                    explodedGraph.add_edges(layer)

                    self.segm_progress.emit(30)

                    self.total = 30
                    step = 65/ max(self.explodedGraph.sEdges.keys())
                    explodedGraph.progress.connect(lambda incr=self.add_step(step): self.segm_progress.emit(incr))

                    segments, breakages = self.explodedGraph.break_features(self.settings['stub_ratio'])

                    if self.segm_killed is True or explodedGraph.killed is True: return

                    fields = self.explodedGraph.sEdgesFields

                    # todo errors_list = [[k, [[k], [v[0]]], v[1]] for k, v in self.br.errors_features.items()]

                    #if is_debug:
                    print "survived!"
                    self.segm_progress.emit(100)
                    # return cleaned data, errors and unlinks
                    ret = ((segments, fields), (breakages, breakages_fields))

                except Exception, e:
                    # forward the exception upstream
                    # print 'exception'
                    self.error.emit(e, traceback.format_exc())

            self.finished.emit(ret)

        def kill(self):
            print 'killed'
            self.segm_killed = True
