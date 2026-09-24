from __future__ import annotations

import runpy
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


class DetectionDatasetTests(unittest.TestCase):
    def test_autohdr_names_register_with_original_metadata(self):
        registered = {}

        class Registry:
            def register_module(self):
                def register(cls):
                    registered[cls.__name__] = cls
                    return cls
                return register

        class CocoDataset:
            pass

        datasets = ModuleType('mmdet.datasets')
        datasets.CocoDataset = CocoDataset
        registry = ModuleType('mmdet.registry')
        registry.DATASETS = Registry()
        source = Path(__file__).resolve().parents[1] / 'text_detection/runtime/datasets.py'
        with patch.dict('sys.modules', {
            'mmdet': ModuleType('mmdet'),
            'mmdet.datasets': datasets,
            'mmdet.registry': registry,
        }):
            runpy.run_path(str(source))

        self.assertEqual(set(registered), {'FS_Dataset', 'HDR_Dataset'})
        self.assertTrue(issubclass(registered['FS_Dataset'], CocoDataset))
        self.assertTrue(issubclass(registered['HDR_Dataset'], CocoDataset))
        self.assertEqual(registered['FS_Dataset'].METAINFO, {
            'classes': ('0', '1', '2'),
            'palette': [(220, 20, 60), (119, 11, 32), (0, 0, 142)],
        })
        self.assertEqual(registered['HDR_Dataset'].METAINFO, {
            'classes': ('0',),
            'palette': [(220, 20, 60)],
        })
