"""Shared PDF/image assembly; originals are never modified."""

def append_document(target, document, source_path):
    import fitz
    if source_path.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
        with fitz.open('pdf', document.convert_to_pdf()) as image_pdf:
            target.insert_pdf(image_pdf)
    else:
        # insert_pdf in older supported runtimes drops widgets. Bake before
        # insertion, not only after assembling the destination document.
        with fitz.open(stream=document.tobytes(), filetype='pdf') as copy:
            _bake_visible(copy)
            target.insert_pdf(copy)


def _bake_visible(document):
    if any(page.first_annot or page.first_widget for page in document):
        if not hasattr(document, 'bake'):
            raise ValueError('PDF批注保留需要PyMuPDF 1.24.2或更新版本')
        document.bake(annots=True, widgets=True)


def numbered_copy(document, label='Stella'):
    """Normalize visible rotated/cropped pages into copies with a new footer margin."""
    import fitz
    result = fitz.open()
    # show_pdf_page omits annotations/widgets. Flatten only a private copy so
    # visible stamps, ink and form values survive page normalization.
    flattened = fitz.open(stream=document.tobytes(), filetype='pdf')
    try:
        _bake_visible(flattened)
        for index, original in enumerate(flattened):
            box = original.rect
            page = result.new_page(width=box.width, height=box.height + 24)
            # Blank pages have no contents for show_pdf_page, but still retain a folio.
            if original.get_contents():
                rotation = original.rotation
                # show_pdf_page measures the source's unrotated box. Reset the
                # in-memory compiled copy, apply its view rotation, then restore.
                original.set_rotation(0)
                try:
                    page.show_pdf_page(fitz.Rect(0, 0, box.width, box.height), flattened, index, rotate=-rotation)
                finally:
                    original.set_rotation(rotation)
            page.insert_text((12, box.height + 16), f'{label}  /  {index + 1}', fontsize=9, color=(.3,.3,.3))
        return result
    except Exception:
        result.close()
        raise
    finally:
        flattened.close()
