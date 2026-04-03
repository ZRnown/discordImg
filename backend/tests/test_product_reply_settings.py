import json
import unittest

from backend.product_reply_settings import resolve_effective_product_reply_settings


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


if __name__ == '__main__':
    unittest.main()
