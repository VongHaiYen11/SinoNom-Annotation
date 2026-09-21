"""Public inference-only AutoHDR character detector."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import cv2
import numpy as np
import torch
import torchvision
from .model_client import DetectorModelClient
from .reading_order import sort_boxes_reading_order

@dataclass(frozen=True)
class CharacterDetection:
    bbox_xyxy: tuple[int,int,int,int]
    confidence: float
    corners: tuple[tuple[int,int],tuple[int,int],tuple[int,int],tuple[int,int]]

@dataclass(frozen=True)
class DetectionResult:
    image_size: tuple[int,int]
    detections: list[CharacterDetection]

def _letterbox(image, size, stride):
    h,w=image.shape[:2]; r=min(size/h,size/w); unpad=(int(round(w*r)),int(round(h*r))); dw,dh=np.mod((size-unpad[0],size-unpad[1]),stride); dw,dh=dw/2,dh/2
    if (w,h)!=unpad: image=cv2.resize(image,unpad,interpolation=cv2.INTER_LINEAR)
    return cv2.copyMakeBorder(image,int(round(dh-.1)),int(round(dh+.1)),int(round(dw-.1)),int(round(dw+.1)),cv2.BORDER_CONSTANT,value=(114,114,114))

def _nms(prediction, conf, iou):
    output=[]
    for x in prediction:
        x=x[x[:,4]>conf]
        if not len(x): output.append(torch.zeros((0,6),device=prediction.device)); continue
        nc=x.shape[1]-5
        if nc==1: x[:,5:]=x[:,4:5]
        else: x[:,5:]*=x[:,4:5]
        b=x[:,:4].clone(); b[:,0]=x[:,0]-x[:,2]/2; b[:,1]=x[:,1]-x[:,3]/2; b[:,2]=x[:,0]+x[:,2]/2; b[:,3]=x[:,1]+x[:,3]/2
        ii,jj=(x[:,5:]>conf).nonzero(as_tuple=False).T; x=torch.cat((b[ii],x[ii,jj+5,None],jj[:,None].float()),1)
        offsets=x[:,5:6]*4096; output.append(x[torchvision.ops.nms(x[:,:4]+offsets,x[:,4],iou)[:5000]])
    return output

def _scale(boxes, model_shape, original_shape):
    gain=min(model_shape[0]/original_shape[0],model_shape[1]/original_shape[1]); pad=((model_shape[1]-original_shape[1]*gain)/2,(model_shape[0]-original_shape[0]*gain)/2)
    boxes[:,[0,2]]-=pad[0]; boxes[:,[1,3]]-=pad[1]; boxes[:,:4]/=gain
    boxes[:,0].clamp_(0,original_shape[1]); boxes[:,1].clamp_(0,original_shape[0]); boxes[:,2].clamp_(0,original_shape[1]); boxes[:,3].clamp_(0,original_shape[0])

class CharacterDetector:
    """YOLOv7 detector with AutoHDR's original inference transforms and NMS."""
    def __init__(self, detector_executable: str|Path, *, device: str|None=None, image_size=2048, confidence_threshold=.45, iou_threshold=.20, invert=True, port=12345):
        self.device=torch.device(device or ('cuda' if torch.cuda.is_available() else 'cpu')); self.image_size=image_size; self.confidence_threshold=confidence_threshold; self.iou_threshold=iou_threshold; self.invert=invert; self.client=DetectorModelClient(detector_executable,port)
    def detect(self, image: str|Path|np.ndarray, *, reading_order=True) -> DetectionResult:
        original=cv2.imread(str(image)) if isinstance(image,(str,Path)) else image
        if original is None: raise FileNotFoundError(f'Could not read image: {image}')
        if original.ndim!=3 or original.shape[2]!=3: raise ValueError('Expected BGR image with shape (H, W, 3)')
        source=255-original if self.invert else original; stride=self.client(self.device,mode=1); size=int(np.ceil(self.image_size/int(stride))*int(stride)); prepared=_letterbox(source,size,stride)
        tensor=torch.from_numpy(np.ascontiguousarray(prepared[:,:,::-1].transpose(2,0,1))).to(self.device); tensor=tensor.half() if self.device.type!='cpu' else tensor.float(); tensor/=255
        with torch.no_grad(): detections=_nms(self.client(tensor,mode=2),self.confidence_threshold,self.iou_threshold)[0]
        _scale(detections[:,:4],tensor.shape[1:],original.shape[:2]); pairs=[(tuple(round(float(v)) for v in row[:4]),float(row[4])) for row in detections.cpu().numpy().tolist()]
        if reading_order:
            score={box:value for box,value in pairs}; pairs=[(tuple(map(int,b)),score[tuple(map(int,b))]) for b in sort_boxes_reading_order([list(b) for b,_ in pairs],*original.shape[:2])]
        return DetectionResult((original.shape[1],original.shape[0]),[self._token(b,s) for b,s in pairs])
    @staticmethod
    def _token(box: Sequence[int], score: float) -> CharacterDetection:
        x1,y1,x2,y2=map(int,box); return CharacterDetection((x1,y1,x2,y2),score,((x1,y1),(x2,y1),(x2,y2),(x1,y2)))
    def close(self): self.client.close()
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
