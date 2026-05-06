import unittest

from backend.product_category import infer_product_category


class ProductCategoryTestCase(unittest.TestCase):
    def test_infers_core_apparel_and_accessory_categories(self):
        self.assertEqual(infer_product_category("LV 老花 单肩包"), "bag")
        self.assertEqual(infer_product_category("Nike running shoes"), "shoe")
        self.assertEqual(infer_product_category("足球训练服套装"), "top")
        self.assertEqual(infer_product_category("CP短裤"), "pants")
        self.assertEqual(infer_product_category("Rolex 手表"), "watch")

    def test_unknown_category_stays_empty(self):
        self.assertEqual(infer_product_category("random product"), "")


if __name__ == "__main__":
    unittest.main()
