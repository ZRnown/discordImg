import json
import unittest

from backend.product_reply_settings import (
    collect_uploaded_reply_filenames,
    resolve_effective_product_reply_settings,
)

try:
    from backend.product_title_translations import (
        apply_reply_language_template_default,
        fill_missing_title_translations,
        get_localized_product_titles,
        get_localized_product_title,
        normalize_enabled_title_languages,
        normalize_reply_language,
        normalize_reply_languages,
        normalize_title_translations,
        render_reply_template,
    )
except ModuleNotFoundError:
    apply_reply_language_template_default = None
    fill_missing_title_translations = None
    get_localized_product_titles = None
    get_localized_product_title = None
    normalize_enabled_title_languages = None
    normalize_reply_language = None
    normalize_reply_languages = None
    normalize_title_translations = None
    render_reply_template = None

try:
    from backend.keyword_search_terms import (
        build_query_keyword_candidates,
        find_query_keyword_match,
    )
except ModuleNotFoundError:
    build_query_keyword_candidates = None
    find_query_keyword_match = None


class ProductReplySettingsTestCase(unittest.TestCase):
    def test_collect_uploaded_reply_filenames_includes_per_website_uploads(self):
        product = {
            'uploaded_reply_images': json.dumps(['global-a.jpg']),
            'per_website_reply_settings': json.dumps({
                '2': {
                    'uploadedReplyImages': ['site-a.jpg', 'site-b.jpg'],
                },
                '5': {
                    'uploadedReplyImages': ['site-b.jpg', 'site-c.jpg'],
                },
            }),
        }

        self.assertEqual(
            collect_uploaded_reply_filenames(product),
            ['global-a.jpg', 'site-a.jpg', 'site-b.jpg', 'site-c.jpg'],
        )

    def test_website_specific_settings_override_global_settings(self):
        product = {
            'custom_reply_text': 'global text',
            'image_source': 'custom',
            'custom_reply_images': json.dumps([1, 2]),
            'custom_image_urls': json.dumps(['https://global.example/a.jpg']),
            'uploaded_reply_images': json.dumps(['global-upload.jpg']),
            'per_website_reply_settings': json.dumps({
                '2': {
                    'customReplyText': 'website text',
                    'imageSource': 'upload',
                    'selectedImageIndexes': [5],
                    'customImageUrls': ['https://website.example/only.jpg'],
                    'uploadedReplyImages': ['website-upload.jpg'],
                }
            }),
        }

        resolved = resolve_effective_product_reply_settings(product, {'id': 2, 'name': 'cnfans'})

        self.assertEqual(resolved['customReplyText'], 'website text')
        self.assertEqual(resolved['imageSource'], 'upload')
        self.assertEqual(resolved['selectedImageIndexes'], [5])
        self.assertEqual(resolved['customImageUrls'], ['https://website.example/only.jpg'])
        self.assertEqual(resolved['uploadedReplyImages'], ['website-upload.jpg'])

    def test_global_settings_are_used_when_no_per_website_settings_exist(self):
        product = {
            'custom_reply_text': 'global text',
            'image_source': 'custom',
            'custom_reply_images': json.dumps([0]),
            'custom_image_urls': json.dumps(['https://global.example/a.jpg']),
            'uploaded_reply_images': json.dumps(['global-upload.jpg']),
            'per_website_reply_settings': None,
        }

        resolved = resolve_effective_product_reply_settings(product, {'id': 3, 'name': 'acbuy'})

        self.assertEqual(resolved['customReplyText'], 'global text')
        self.assertEqual(resolved['imageSource'], 'custom')
        self.assertEqual(resolved['selectedImageIndexes'], [0])
        self.assertEqual(resolved['customImageUrls'], ['https://global.example/a.jpg'])
        self.assertEqual(resolved['uploadedReplyImages'], ['global-upload.jpg'])

    def test_missing_site_entry_does_not_inherit_global_once_per_website_settings_exist(self):
        product = {
            'custom_reply_text': 'legacy global text',
            'image_source': 'custom',
            'custom_image_urls': json.dumps(['https://global.example/a.jpg']),
            'per_website_reply_settings': json.dumps({
                '2': {
                    'customReplyText': 'cnfans only',
                    'imageSource': 'custom',
                    'customImageUrls': ['https://website.example/only.jpg'],
                }
            }),
        }

        resolved = resolve_effective_product_reply_settings(product, {'id': 5, 'name': 'acbuy'})

        self.assertEqual(resolved['customReplyText'], 'legacy global text')
        self.assertEqual(resolved['imageSource'], 'custom')
        self.assertEqual(resolved['selectedImageIndexes'], [])
        self.assertEqual(resolved['customImageUrls'], ['https://global.example/a.jpg'])
        self.assertEqual(resolved['uploadedReplyImages'], [])

    def test_empty_site_entry_falls_back_to_global_settings(self):
        product = {
            'custom_reply_text': 'shared text',
            'image_source': 'upload',
            'uploaded_reply_images': json.dumps(['shared-upload.jpg']),
            'per_website_reply_settings': json.dumps({
                '2': {
                    'customReplyText': '',
                    'imageSource': 'product',
                    'selectedImageIndexes': [],
                    'customImageUrls': [],
                    'uploadedReplyImages': [],
                }
            }),
        }

        resolved = resolve_effective_product_reply_settings(product, {'id': 2, 'name': 'cnfans'})

        self.assertEqual(resolved['customReplyText'], 'shared text')
        self.assertEqual(resolved['imageSource'], 'upload')
        self.assertEqual(resolved['selectedImageIndexes'], [])
        self.assertEqual(resolved['customImageUrls'], [])
        self.assertEqual(resolved['uploadedReplyImages'], ['shared-upload.jpg'])

    def test_uploaded_site_images_without_explicit_source_infer_upload_mode(self):
        product = {
            'image_source': 'product',
            'per_website_reply_settings': json.dumps({
                '2': {
                    'customReplyText': 'website text',
                    'uploadedReplyImages': ['website-upload.jpg'],
                }
            }),
        }

        resolved = resolve_effective_product_reply_settings(product, {'id': 2, 'name': 'cnfans'})

        self.assertEqual(resolved['customReplyText'], 'website text')
        self.assertEqual(resolved['imageSource'], 'upload')
        self.assertEqual(resolved['uploadedReplyImages'], ['website-upload.jpg'])

    def test_custom_url_site_images_without_explicit_source_infer_custom_mode(self):
        product = {
            'image_source': 'product',
            'per_website_reply_settings': json.dumps({
                '2': {
                    'customImageUrls': ['https://website.example/custom.jpg'],
                }
            }),
        }

        resolved = resolve_effective_product_reply_settings(product, {'id': 2, 'name': 'cnfans'})

        self.assertEqual(resolved['imageSource'], 'custom')
        self.assertEqual(resolved['customImageUrls'], ['https://website.example/custom.jpg'])


class ProductTitleTranslationTestCase(unittest.TestCase):
    def test_title_translation_helpers_exist(self):
        self.assertIsNotNone(normalize_reply_language)
        self.assertIsNotNone(normalize_enabled_title_languages)
        self.assertIsNotNone(normalize_reply_languages)
        self.assertIsNotNone(normalize_title_translations)
        self.assertIsNotNone(get_localized_product_titles)
        self.assertIsNotNone(get_localized_product_title)
        self.assertIsNotNone(fill_missing_title_translations)
        self.assertIsNotNone(render_reply_template)
        self.assertIsNotNone(apply_reply_language_template_default)
        self.assertIsNotNone(build_query_keyword_candidates)
        self.assertIsNotNone(find_query_keyword_match)

    def test_normalize_title_translations_keeps_zh_en_fallbacks(self):
        normalized = normalize_title_translations(
            json.dumps({
                'es': 'Zapatillas',
                'fr': 'Chaussures',
            }),
            title='运动鞋',
            english_title='Sneakers',
        )

        self.assertEqual(normalized['zh'], '运动鞋')
        self.assertEqual(normalized['en'], 'Sneakers')
        self.assertEqual(normalized['es'], 'Zapatillas')
        self.assertEqual(normalized['fr'], 'Chaussures')

    def test_normalize_enabled_and_reply_languages_support_portuguese_and_arrays(self):
        self.assertEqual(normalize_enabled_title_languages(None), ['en'])
        self.assertEqual(
            normalize_enabled_title_languages(['pt', 'es']),
            ['en', 'pt', 'es'],
        )
        self.assertEqual(
            normalize_reply_languages(json.dumps(['pt', 'es'])),
            ['pt', 'es'],
        )
        self.assertEqual(
            normalize_reply_languages(None, legacy_reply_language='link_only'),
            [],
        )
        self.assertEqual(
            normalize_reply_languages(None, legacy_reply_language='fr'),
            ['fr'],
        )

    def test_localized_title_prefers_requested_language_then_falls_back(self):
        product = {
            'title': '运动鞋',
            'english_title': 'Sneakers',
            'title_translations': json.dumps({
                'es': 'Zapatillas',
            }),
        }

        self.assertEqual(get_localized_product_title(product, 'es'), 'Zapatillas')
        self.assertEqual(get_localized_product_title(product, 'de'), 'Sneakers')
        self.assertEqual(get_localized_product_title(product, 'link_only'), 'Sneakers')

    def test_localized_titles_join_selected_reply_languages_for_title_placeholder(self):
        product = {
            'title': '运动鞋',
            'english_title': 'Sneakers',
            'title_translations': json.dumps({
                'pt': 'Tenis',
                'es': 'Zapatillas',
            }),
        }

        self.assertEqual(
            get_localized_product_titles(product, ['pt', 'es']),
            ['Tenis', 'Zapatillas'],
        )
        self.assertEqual(
            render_reply_template(
                '{title}\n{url}',
                'https://example.com/p/1',
                product,
                reply_languages=['pt', 'es'],
            ),
            'Tenis / Zapatillas\nhttps://example.com/p/1',
        )

    def test_render_reply_template_uses_selected_language_and_named_placeholders(self):
        product = {
            'title': '运动鞋',
            'english_title': 'Sneakers',
            'title_translations': json.dumps({
                'es': 'Zapatillas',
                'fr': 'Chaussures',
            }),
        }

        rendered = render_reply_template(
            '{title}\n{url}\nFR:{title_fr}\nZH:{title_zh}',
            'https://example.com/p/1',
            product,
            'es',
        )

        self.assertEqual(
            rendered,
            'Zapatillas\nhttps://example.com/p/1\nFR:Chaussures\nZH:运动鞋',
        )

    def test_fill_missing_title_translations_uses_translator_for_enabled_languages(self):
        calls = []

        def fake_translator(text, language):
            calls.append((text, language))
            return {
                'en': 'Sneakers',
                'pt': 'Tenis',
            }.get(language, '')

        filled = fill_missing_title_translations(
            {},
            title='运动鞋',
            english_title='',
            enabled_languages=['pt'],
            translator=fake_translator,
        )

        self.assertEqual(filled['zh'], '运动鞋')
        self.assertEqual(filled['en'], 'Sneakers')
        self.assertEqual(filled['pt'], 'Tenis')
        self.assertEqual(calls, [('运动鞋', 'en'), ('运动鞋', 'pt')])

    def test_keyword_matching_uses_translated_titles(self):
        candidates = build_query_keyword_candidates('tênis')
        matched = find_query_keyword_match(
            candidates,
            english_title='Sneakers',
            title='运动鞋',
            title_translations=json.dumps({
                'ru': 'Теннисные кроссовки',
                'pt': 'Tênis de corrida',
            }),
        )

        self.assertIsNotNone(matched)
        self.assertEqual(matched['source'], 'title_translation:pt')
        self.assertEqual(matched['phrase'], 'tênis')

    def test_keyword_matching_only_uses_languages_enabled_for_current_website(self):
        japanese_candidates = build_query_keyword_candidates('スニーカー')
        japanese_match = find_query_keyword_match(
            japanese_candidates,
            english_title='Sneakers',
            title='运动鞋',
            title_translations=json.dumps({
                'pt': 'Tênis de corrida',
                'ja': 'スニーカー',
            }),
            allowed_languages=['ja'],
        )

        portuguese_candidates = build_query_keyword_candidates('tênis')
        portuguese_match = find_query_keyword_match(
            portuguese_candidates,
            english_title='Sneakers',
            title='运动鞋',
            title_translations=json.dumps({
                'pt': 'Tênis de corrida',
                'ja': 'スニーカー',
            }),
            allowed_languages=['ja'],
        )

        self.assertIsNotNone(japanese_match)
        self.assertEqual(japanese_match['source'], 'title_translation:ja')
        self.assertIsNone(portuguese_match)

    def test_reply_language_default_template_switches_with_language_mode(self):
        self.assertEqual(apply_reply_language_template_default('{url}', 'es'), '{title}\n{url}')
        self.assertEqual(
            apply_reply_language_template_default('{url}', reply_languages=['pt', 'es']),
            '{url}',
        )
        self.assertEqual(apply_reply_language_template_default('{title}\n{url}', 'link_only'), '{url}')
        self.assertEqual(
            apply_reply_language_template_default('{title}\n{url}', reply_languages=[]),
            '{url}',
        )
        self.assertEqual(normalize_reply_language('unknown'), 'link_only')


if __name__ == '__main__':
    unittest.main()
