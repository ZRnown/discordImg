import os
import tempfile
import unittest

from backend.database import Database


class WebsitePostingDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'metadata.db')
        self.db = Database(db_path=self.db_path)

        with self.db.get_connection() as conn:
            conn.execute(
                '''
                INSERT INTO users (username, password_hash, role)
                VALUES (?, ?, ?)
                ''',
                ('posting-user', 'hash', 'user'),
            )
            conn.commit()
            self.user_id = conn.execute(
                'SELECT id FROM users WHERE username = ?',
                ('posting-user',),
            ).fetchone()['id']

        added, error = self.db.add_website_config(
            name='posting-site',
            display_name='Posting Site',
            url_template='https://example.com/{id}',
            id_pattern='{id}',
            badge_color='blue',
            reply_template='{url}',
        )
        self.assertTrue(added, error)
        self.website_id = self.db.get_website_configs()[0]['id']

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_post_library_crud_keeps_category_content_and_images(self):
        entry_id = self.db.add_website_post_library_entry(
            website_id=self.website_id,
            user_id=self.user_id,
            title='衣服帖子 1',
            category='衣服',
            content='第一条帖子内容',
            image_filenames=['look1.jpg', 'look2.png'],
            is_active=1,
        )

        entries = self.db.get_website_post_library(self.website_id, self.user_id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['id'], entry_id)
        self.assertEqual(entries[0]['category'], '衣服')
        self.assertEqual(entries[0]['content'], '第一条帖子内容')
        self.assertEqual(entries[0]['image_filenames'], ['look1.jpg', 'look2.png'])

        updated = self.db.update_website_post_library_entry(
            post_id=entry_id,
            website_id=self.website_id,
            user_id=self.user_id,
            title='鞋子帖子 1',
            category='鞋子',
            content='改过后的帖子内容',
            image_filenames=['shoe1.jpg'],
            is_active=0,
        )
        self.assertTrue(updated)

        updated_entry = self.db.get_website_post_library(self.website_id, self.user_id)[0]
        self.assertEqual(updated_entry['title'], '鞋子帖子 1')
        self.assertEqual(updated_entry['category'], '鞋子')
        self.assertEqual(updated_entry['content'], '改过后的帖子内容')
        self.assertEqual(updated_entry['image_filenames'], ['shoe1.jpg'])
        self.assertEqual(updated_entry['is_active'], 0)

        removed = self.db.delete_website_post_library_entry(
            post_id=entry_id,
            website_id=self.website_id,
            user_id=self.user_id,
        )
        self.assertTrue(removed)
        self.assertEqual(self.db.get_website_post_library(self.website_id, self.user_id), [])

    def test_schedule_selection_respects_category_and_wraps_in_sequential_mode(self):
        first_post_id = self.db.add_website_post_library_entry(
            website_id=self.website_id,
            user_id=self.user_id,
            title='衣服帖子 1',
            category='衣服',
            content='A',
            image_filenames=[],
            is_active=1,
        )
        second_post_id = self.db.add_website_post_library_entry(
            website_id=self.website_id,
            user_id=self.user_id,
            title='衣服帖子 2',
            category='衣服',
            content='B',
            image_filenames=[],
            is_active=1,
        )
        self.db.add_website_post_library_entry(
            website_id=self.website_id,
            user_id=self.user_id,
            title='鞋子帖子 1',
            category='鞋子',
            content='C',
            image_filenames=[],
            is_active=1,
        )

        schedule_id = self.db.add_website_post_schedule(
            website_id=self.website_id,
            user_id=self.user_id,
            channel_id='123456789012345678',
            category='衣服',
            send_mode='sequential',
            interval_minutes=30,
            enabled=1,
        )

        due_schedules = self.db.get_due_website_post_schedules()
        self.assertEqual([item['id'] for item in due_schedules], [schedule_id])

        first_choice = self.db.select_website_post_for_schedule(schedule_id, self.user_id)
        self.assertIsNotNone(first_choice)
        self.assertEqual(first_choice['id'], first_post_id)

        marked_first = self.db.mark_website_post_schedule_sent(
            schedule_id=schedule_id,
            user_id=self.user_id,
            post_id=first_post_id,
        )
        self.assertTrue(marked_first)

        second_choice = self.db.select_website_post_for_schedule(schedule_id, self.user_id)
        self.assertIsNotNone(second_choice)
        self.assertEqual(second_choice['id'], second_post_id)

        marked_second = self.db.mark_website_post_schedule_sent(
            schedule_id=schedule_id,
            user_id=self.user_id,
            post_id=second_post_id,
        )
        self.assertTrue(marked_second)

        wrapped_choice = self.db.select_website_post_for_schedule(schedule_id, self.user_id)
        self.assertIsNotNone(wrapped_choice)
        self.assertEqual(wrapped_choice['id'], first_post_id)

    def test_post_stats_accumulate_total_and_daily_counts(self):
        self.assertTrue(
            self.db.increment_user_website_post_stats(self.user_id, self.website_id)
        )
        self.assertTrue(
            self.db.increment_user_website_post_stats(self.user_id, self.website_id)
        )

        stats_map = self.db.get_user_website_post_stats_map(self.user_id, [self.website_id])
        self.assertEqual(
            stats_map[self.website_id],
            {
                'stat_posts_total': 2,
                'stat_posts_daily_total': 2,
            },
        )


if __name__ == '__main__':
    unittest.main()
