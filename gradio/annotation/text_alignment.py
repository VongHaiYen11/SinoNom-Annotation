"""One normalization policy shared by counting and alignment."""
import unicodedata
import regex


def normalize_annotation_text(text):
    return ''.join(c for c in unicodedata.normalize('NFC', text)
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


def characters(text):
    return regex.findall(r'\X', normalize_annotation_text(text))


def count_annotation_characters(text):
    return len(characters(text))


def temporary_align_text(box_ids, text):
    ids = [str(i) for i in box_ids]
    chars = characters(text)
    if not chars or len(ids) != len(chars) or len(set(ids)) != len(ids):
        raise ValueError('Box and character counts must match and be nonzero; IDs must be unique.')
    return dict(zip(ids, chars))


def validate_bbox_text_count(state):
    return bool(characters(state['annotation_text'])) and len(state['bounding_boxes']) == count_annotation_characters(state['annotation_text'])
