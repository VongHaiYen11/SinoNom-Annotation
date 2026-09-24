# Copyright (c) OpenMMLab. All rights reserved.
"""AutoHDR dataset metadata extracted from datasets/fssj.py and hdr.py.

Their annotation methods match CocoDataset; only metadata is customized.
Import this module before init_detector builds the configured test dataset.
"""

from mmdet.datasets import CocoDataset
from mmdet.registry import DATASETS


@DATASETS.register_module()
class FS_Dataset(CocoDataset):
    METAINFO = {
        'classes': ('0', '1', '2'),
        'palette': [(220, 20, 60), (119, 11, 32), (0, 0, 142)],
    }


@DATASETS.register_module()
class HDR_Dataset(CocoDataset):
    METAINFO = {
        'classes': ('0',),
        'palette': [(220, 20, 60)],
    }
