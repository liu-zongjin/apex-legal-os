"""Shared PDF/image assembly; originals are never modified."""

def append_document(target, document, source_path):
    import fitz
    if source_path.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
        with fitz.open('pdf', document.convert_to_pdf()) as image_pdf:
            target.insert_pdf(image_pdf)
    else:
        target.insert_pdf(document)


def numbered_copy(document, label='Stella'):
    """Normalize visible rotated/cropped pages into copies with a new footer margin."""
    import fitz
    result = fitz.open()
    try:
        for index, original in enumerate(document):
            box = original.rect
            page = result.new_page(width=box.width, height=box.height + 24)
            # Blank pages have no contents for show_pdf_page, but still retain a folio.
            if original.get_contents():
                rotation = original.rotation
                # show_pdf_page measures the source's unrotated box. Reset the
                # in-memory compiled copy, apply its view rotation, then restore.
                original.set_rotation(0)
                try:
                    page.show_pdf_page(fitz.Rect(0, 0, box.width, box.height), document, index, rotate=-rotation)
                finally:
                    original.set_rotation(rotation)
            page.insert_text((12, box.height + 16), f'{label}  /  {index + 1}', fontsize=9, color=(.3,.3,.3))
        return result
    except Exception:
        result.close()
        raise
