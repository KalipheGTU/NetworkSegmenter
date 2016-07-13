# -*- coding: utf-8 -*-
"""
/***************************************************************************
 NetworkSegmenterDialog
                                 A QGIS plugin
 Breaking a network into segments while removing stubbs and reading unlinks
                             -------------------
        begin                : 2016-07-06
        git sha              : $Format:%H$
        copyright            : (C) 2016 by Laurens Versluis
        email                : l.versluis@spacesyntax.com
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

import os

from PyQt4 import QtGui, uic

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'network_segmenter_dialog_base.ui'))


class NetworkSegmenterDialog(QtGui.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(NetworkSegmenterDialog, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)

        self.networkText.setPlaceholderText("Save as temporary layer...")
        self.networkSaveButton.clicked.connect(self.setNetworkOutput)

        # Setup the progress bar
        self.analysisProgress.setMinimum(0)
        self.analysisProgress.setMaximum(5)

    def setNetworkLayers(self, names):
        layers = ['-----']
        if names:
            layers = []
            layers.extend(names)
        self.networkCombo.clear()
        self.networkCombo.addItems(layers)


    def getNetwork(self):
        return self.networkCombo.currentText()


    def setUnlinkLayers(self, names):
        layers = ['-----']
        if names:
            layers = []
            layers.extend(names)
        self.unlinkCombo.clear()
        self.unlinkCombo.addItems(layers)


    def getUnlinks(self):
        return self.unlinkCombo.currentText()


    def getStubRatio(self):
        return self.stubSpin.value()

    def setNetworkOutput(self):
        file_name = QtGui.QFileDialog.getSaveFileName(self, "Save output file ", "segment_network", '*.shp')
        if file_name:
            self.networkText.setText(file_name)


    def getNetworkOutput(self):
        return self.networkText.text()


    def closeDialog(self):
        self.networkCombo.clear()
        self.unlinkCombo.clear()
        self.stubSpin.setValue(0.25)
        self.networkText.clear()
        self.analysisProgress.reset()
        self.close()
