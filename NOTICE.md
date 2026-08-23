# Notices and attribution

LightBox includes work from several sources, and they are not all under the same
licence. The MIT licence in `LICENSE` covers **the LightBox application code only**.
It does not cover the reading books or the video lessons. Those keep their own terms,
listed below.

If you redistribute LightBox, or anything you build from it, these terms travel with
the content.

## 1. LightBox application code

Everything under `app/`, `server/`, `tools/`, and `scripts/` is MIT licensed. See
`LICENSE`.

## 2. Reading books, under `books/`

85 books from three sources. All may be redistributed.

| Prefix | Titles | Source | Licence |
|---|---|---|---|
| `asp_` | 30 | African Storybook Project, via Global ASP | CC BY 4.0 |
| `pb_` | 25 | Pratham Books / StoryWeaver, via Global ASP | CC BY 4.0 |
| `gb` | 30 | Project Gutenberg | Public domain |

- <https://www.africanstorybook.org>
- <https://storyweaver.org.in>
- <https://www.gutenberg.org/policy/license.html>

CC BY requires attribution. Every book carries its author, illustrator, source URL,
and licence in its JSON file, and LightBox shows that credit on the book itself. If
you add, edit, or move books, keep those fields intact.

Some non-English versions of these books were produced by machine translation with
LibreTranslate and are marked `"mt": true` in their JSON. They are derivative works
of the CC BY originals and carry the same licence and attribution.

## 3. Video lessons and captions, downloaded into `content/`

127 grade K to 8 maths lessons from **Khan Academy**, with captions, licensed
**CC BY-NC-SA 4.0**.

- <https://www.khanacademy.org>
- <https://creativecommons.org/licenses/by-nc-sa/4.0/>

These are not stored in this repository. `scripts/fetch_content.py` downloads them
during installation, and `server/install.sh` calls it for you.

CC BY-NC-SA sets three conditions. If you share these lessons you must credit Khan
Academy, you may not sell them or use them commercially, and anything you adapt from
them must carry the same licence.

`transcripts/` is plain text generated from those captions by `app/prep.py`, so it
carries the same terms.

## 4. Bundled fonts, under `app/static/fonts/`

**Baloo 2**, **Lexend**, and **Literata**, all under the SIL Open Font License 1.1.

- <https://openfontlicense.org>

## 5. Software LightBox runs alongside

These are downloaded and built on your own machine by `server/install.sh`. LightBox
does not redistribute them.

- **llama.cpp**, MIT, <https://github.com/ggml-org/llama.cpp>
- **Qwen2.5-3B-Instruct**, see the licence on its Hugging Face model card
- **LibreTranslate**, AGPL-3.0, <https://github.com/LibreTranslate/LibreTranslate>
