"""Build a folder export exclusively from per-image files saved in Review."""
from pathlib import Path
import hashlib
import json
import zipfile

from PIL import Image

from .io import load_annotation, read_json
from .text_extraction import validate_content_document
from crop.crop import crop_document, crop_bbox, default_crop


EXPORT_ARCHIVE_NAME = 'annotations.zip'


def save_export_archive(annotations, content, output_dir):
    """Persist the Save-all payload as one ZIP and return its path."""
    documents = {}
    if annotations:
        documents['text_annotations.json'] = annotations
    if content:
        documents['inscription_content.json'] = content
    if not documents:
        raise ValueError('No image or content records have been saved yet.')

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / EXPORT_ARCHIVE_NAME
    temporary = archive.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, data in documents.items():
                bundle.writestr(name, json.dumps(data, ensure_ascii=False, indent=2))
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def collect_annotations(images, output_dir, allow_empty=False):
    if not images:
        raise ValueError('The image folder is empty.')
    documents, errors = [], []
    for image_path in images:
        path = Path(image_path).resolve()
        saved = Path(output_dir) / (path.stem + '.json')
        # An image becomes part of Save all only after Save image creates this file.
        if not saved.exists():
            continue
        try:
            with Image.open(path) as image:
                size = list(image.size)
            doc = load_annotation(saved, path.name, size)
            if not doc.get('annotations'):
                raise ValueError('Character annotations are missing.')
            meta_path = Path(output_dir) / '.state' / saved.name
            if meta_path.exists():
                meta = read_json(meta_path)
                digest = hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
                if meta.get('document_hash') != digest:
                    raise ValueError('Saved annotation was changed outside the Review save flow.')
            # Legacy files stored crop separately. A missing legacy crop means full image.
            if 'crop' not in doc:
                crop_path = Path(output_dir) / 'crops' / saved.name
                bbox = default_crop(size)
                if crop_path.exists():
                    crop = read_json(crop_path)
                    if crop['image'] != path.name:
                        raise ValueError('Crop belongs to another image.')
                    bbox = crop_bbox(crop['crop'], size)
                doc['crop'] = crop_document(path.name, bbox, size)['crop']
            documents.append(doc)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(f'{path.name}: {exc}')
    if errors:
        raise ValueError('Cannot export the saved annotations:\n' + '\n'.join(errors))
    if not documents and not allow_empty:
        raise ValueError('No images have been saved from Review yet.')
    return documents


def collect_content_documents(images, output_dir, allow_empty=False):
    """Collect only documents explicitly committed with Save content."""
    if not images:
        raise ValueError('The image folder is empty.')
    registry = Path(output_dir) / '.state' / 'content.json'
    if not registry.exists():
        documents = []
    else:
        saved_documents = read_json(registry)
        if not isinstance(saved_documents, list):
            raise ValueError('The saved-content registry must be a JSON array.')
        by_image = {}
        for document in saved_documents:
            validate_content_document(document, document.get('image') if isinstance(document, dict) else '')
            if document['image'] in by_image:
                raise ValueError('The saved-content registry contains duplicate images.')
            by_image[document['image']] = document
        documents = [by_image[path.name] for path in map(Path, images) if path.name in by_image]
    if not documents and not allow_empty:
        raise ValueError('No content has been saved from Content Verification yet.')
    return documents
