import json
import unittest

from backend.product_reply_settings import resolve_effective_product_reply_settings

try:
    from backend.product_title_translations import (
        apply_reply_language_template_default,
        get_localized_product_title,
        normalize_reply_language,
        normalize_title_translations,
        render_reply_template,
    )
except ModuleNotFoundError:
    apply_reply_language_template_default = None
    get_localized_product_title = None
    normalize_reply_language = None
    normalize_title_translations = None
    render_reply_template = None


class ProductReplySettingsTestCase(unittest.TestCase):
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


class ProductTitleTranslationTestCase(unittest.TestCase):
    def test_title_translation_helpers_exist(self):
        self.assertIsNotNone(normalize_reply_language)
        self.assertIsNotNone(normalize_title_translations)
        self.assertIsNotNone(get_localized_product_title)
        self.assertIsNotNone(render_reply_template)
        self.assertIsNotNone(apply_reply_language_template_default)

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

    def test_reply_language_default_template_switches_with_language_mode(self):
        self.assertEqual(apply_reply_language_template_default('{url}', 'es'), '{title}\n{url}')
        self.assertEqual(apply_reply_language_template_default('{title}\n{url}', 'link_only'), '{url}')
        self.assertEqual(normalize_reply_language('unknown'), 'link_only')


if __name__ == '__main__':
    unittest.main()
