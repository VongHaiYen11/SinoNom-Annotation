"""Coordinate-only reading-order heuristic extracted from ``utils.reader``."""

from __future__ import annotations

import cv2
import numpy as np
from shapely.geometry import Polygon


def _coors(a): return np.array(a)[:, :4].astype('float64')

def _poly(coors, shape):
    h, w = shape; s = 4; mask = np.zeros((int(h/s), int(w/s)))
    cv2.fillPoly(mask, [(coors[:, [0,1,2,1,2,3,0,3]]/s).astype(np.int32).reshape(-1,1,2)], color=(1,))
    p = np.where(mask == 1); p = np.concatenate([p[1][:,None], p[0][:,None]], 1)
    b = np.intp(cv2.boxPoints(cv2.minAreaRect(np.array([p]))))
    center = np.sum(b, 0) / 4
    return b[np.argsort(np.arctan2(b[:,1]-center[1], b[:,0]-center[0]))].reshape(-1) * s

def _components(inter, groups):
    while True:
        out=[]; used=[False]*len(inter)
        for i in range(len(inter)):
            if used[i]: continue
            used[i]=True; cur=inter[i]
            for j in range(i+1,len(inter)):
                if not used[j] and any(v in cur for v in inter[j]): cur.extend(inter[j]); used[j]=True
            out.append(list(set(cur)))
        if len(set(v for x in out for v in x)) == sum(map(len,out)): break
        inter=out
    result=[]
    for ids in out:
        values=np.vstack([groups[i] for i in ids]); _, ix=np.unique(_coors(values),axis=0,return_index=True); result.append(values[ix])
    return result

def _merge1(values, threshold=10):
    boxes=_coors(values); marked=[False]*len(values); result=[]
    for i in range(len(values)):
        if marked[i]: continue
        marked[i]=True; current=[values[i]]; adding=True
        while adding:
            adding=False; c=_coors(current); xmin,xmax,ymin,ymax=min(c[:,0]),max(c[:,2]),min(c[:,1]),max(c[:,3])
            for j, box in enumerate(boxes):
                if not marked[j] and (abs(box[0]-xmin)<=threshold or abs(box[2]-xmax)<=threshold) and (abs(box[1]-ymax)<=threshold or abs(box[3]-ymin)<=threshold): current.append(values[j]); marked[j]=True; adding=True
        result.append(np.array(current))
    return result

def _merge(groups, polys, stage):
    inter=[]
    for i,a in enumerate(polys):
        cur=[i]
        for j in range(i+1,len(polys)):
            b=polys[j]
            horizontal=max(0,min(a[4],b[2])-max(a[6],b[0]))
            limit=.4 if stage==2 else .7
            contains=horizontal/(a[4]-a[6])>limit or horizontal/(b[2]-b[0])>limit
            if stage==2: overlaps=abs(a[1]-b[5])<300 or abs(a[5]-b[1])<300; match=contains and overlaps
            else:
                pa,pb=Polygon(a.reshape(4,2)).convex_hull,Polygon(b.reshape(4,2)).convex_hull; area=pa.intersection(pb).area
                overlaps=max(area/pa.area,area/pb.area)>.3 or (area/min(pa.area,pb.area)>.1 if stage==3 else area/(pa.area+pb.area-area)>.2)
                match=(contains and overlaps) if stage==3 else (contains or overlaps)
            if match: cur.append(j)
        inter.append(cur)
    return _components(inter,groups)

def _small(values, output, shape):
    marked=[False]*len(values); groups=[]; values=np.array(values)
    for i in range(len(values)):
        if marked[i]: continue
        marked[i]=True; current=[values[i]]; adding=True
        while adding:
            adding=False; c=_coors(current)
            for j,b in enumerate(_coors(values)):
                if not marked[j] and (abs(b[0]-min(c[:,0]))<=5 or abs(b[2]-max(c[:,2]))<=5): current.append(values[j]); marked[j]=True; adding=True
        groups.append(np.array(current))
    groups=_merge(groups,[_poly(g[:,:4].astype(np.int16),shape) for g in groups],4)
    for group in sorted(groups,key=lambda g:min(_coors(g)[:,0]),reverse=True): output.extend(group[_coors(group)[:,1].argsort()])
    return groups

def _columns(groups, polys, shape):
    result=[]
    for group,p in sorted(zip(groups,polys),key=lambda x:min(_coors(x[0])[:,0]),reverse=True):
        group=group[_coors(group)[:,1].argsort()]; width=p[2]-p[0]; pts=p.reshape(-1,2); output=[]; small=[]; large=[]; segments=[]
        for i,v in enumerate(group):
            b=v[:4].astype(np.int16); nxt=group[i+1][:4].astype(np.int16) if i<len(group)-1 else np.array([])
            cx=int((b[1]-pts[0][1])/(pts[3][1]-pts[0][1]+1e-4)*(pts[3][0]-pts[0][0])+pts[0][0]+width/2)
            def big(q): return (q[2]-q[0])/width>.6 or (q[0]<=cx<=q[2] and .4<(cx-q[0])/(q[2]-cx+1e-3)<2.5 and (q[2]-q[0])/width>=.45)
            if big(b) or (len(nxt) and not small and big(nxt)) or (not len(nxt) and not small):
                if small: segments.extend(_small(small,output,shape)); small=[]
                output.append(v); large.append(v)
            else:
                if large: segments.append(np.array(large)); large=[]
                small.append(v)
                if i==len(group)-1: segments.extend(_small(small,output,shape))
        if large: segments.append(np.array(large))
        result.append(segments)
    return result

def sort_boxes_reading_order(boxes, image_height: int, image_width: int) -> list[list[float]]:
    """Return ``xyxy`` boxes in the original AutoHDR page reading order."""
    if not boxes: return []
    values=np.asarray(boxes); values=values[(-(values[:,2]-values[:,0])).argsort()]; groups=_merge1(values); shape=(image_height,image_width)
    polys=[_poly(g[:,:4].astype(np.int16),shape) for g in groups]
    for _ in range(5):
        previous_count=len(groups); updated=_merge(groups,polys,2); updated_polys=[_poly(g[:,:4].astype(np.int16),shape) for g in updated]
        groups,polys=updated,updated_polys
        if len(updated)==previous_count: break
    groups=_merge(groups,polys,3); polys=[_poly(g[:,:4].astype(np.int16),shape) for g in groups]
    return [box[:4].tolist() for col in _columns(groups,polys,shape) for segment in col for box in segment]
