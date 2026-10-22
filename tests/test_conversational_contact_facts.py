"""Fictional conversational language; never examples copied from private Messages."""
from test_contact_proposals import ContactProposalFixture


class ConversationalFactTests(ContactProposalFixture):
    def test_conversational_birthdays_and_ordinals_preserve_only_stated_year(self):
        cases = [("Hey! My bday's on June 4th 😊", {'month': 6, 'day': 4}),
                 ('Oh, I was born on the 4th of June, 1992. How about you?', {'month': 6, 'day': 4, 'year': 1992}),
                 ('I have class today. My birthday falls on Sept. 12th!', {'month': 9, 'day': 12}),
                 ("btw my birthday is coming up on March 8", {'month': 3, 'day': 8}),
                 ("My birthday is Feb 29, so I celebrate in March sometimes.", {'month': 2, 'day': 29})]
        for text, expected in cases:
            with self.subTest(text=text):
                rows = self.scan([self.message(text)])
                active = [r for r in rows if r['state'] != 'stale']
                self.assertEqual([expected], [r['value'] for r in active])

    def test_conversational_home_work_and_unlabelled_addresses(self):
        cases = [("Sure, I live at 123 Maple Street. Come by sometime!", 'home'),
                 ("Hey, I just moved to 123 Maple Street, Example City, CA 90000!", 'home'),
                 ('My office is at 456 Oak Avenue, Example City, CA 90000.', 'work'),
                 ("Here's my address: 123 Maple Street", None)]
        for text, label in cases:
            with self.subTest(text=text):
                rows = self.scan([self.message(text)])
                active = [r for r in rows if r['state'] != 'stale']
                self.assertEqual(1, len(active))
                self.assertEqual(label, active[0]['value']['label'])
                if label is None:
                    self.assertEqual('blocked', active[0]['state'])
                    self.assertIn('address_label_unspecified', active[0]['reasons'])

    def test_two_facts_in_one_message_have_independent_exact_evidence(self):
        text = 'My bday is June 4th. I live at 123 Maple Street.'
        rows = self.scan([self.message(text)])
        self.assertEqual({'birthday', 'postal_address'}, {r['field'] for r in rows})
        with self.pipeline() as pipeline:
            spans = {pipeline.show(r['id'])['evidence'][0]['span'] for r in rows}
        self.assertEqual({'June 4th', '123 Maple Street'}, spans)

    def question_answer(self, question='When is your birthday?', answer='June 4th 😊', **overrides):
        chat = [{'guid': 'fictional-chat', 'participants': ['alice@example.test']}]
        q = self.message(question, ident='question', fromMe=True, sender='me', chats=chat)
        q['start'] = '2026-10-02T11:59:00Z'
        a = self.message(answer, chats=[dict(c) for c in chat], **overrides)
        return q, a

    def test_question_answer_requires_same_direct_thread_and_tracks_question_revision(self):
        q, a = self.question_answer()
        rows = self.scan([q, a])
        self.assertEqual(1, len(rows))
        self.assertEqual({'month': 6, 'day': 4}, rows[0]['value'])
        with self.pipeline() as pipeline:
            detail = pipeline.show(rows[0]['id'])
            self.assertEqual('question', detail['evidence'][0]['context_record_id'])
        q['payload']['text'] = 'When is your appointment?'
        self.ingest('message', [q, a])
        with self.pipeline() as pipeline:
            self.assertEqual('stale', pipeline.show(rows[0]['id'])['state'])

    def test_question_answer_address_with_explicit_home_semantics(self):
        q, a = self.question_answer('Where do you live?', '123 Maple Street, Example City, CA 90000')
        rows = self.scan([q, a])
        self.assertEqual(1, len(rows))
        self.assertEqual('home', rows[0]['value']['label'])

    def test_question_context_never_crosses_thread_or_reaches_past_intervening_turn(self):
        q, a = self.question_answer()
        a['payload']['chats'][0]['guid'] = 'other-chat'
        self.assertEqual([], self.scan([q, a]))
        q, a = self.question_answer()
        middle = self.message('When is your appointment?', 'middle', fromMe=True, sender='me',
                              chats=q['payload']['chats'])
        middle['start'] = '2026-10-02T11:59:30Z'
        self.assertEqual([], self.scan([q, middle, a]))
        q, a = self.question_answer()
        q['start'] = '2026-09-30T11:59:00Z'
        self.assertEqual([], self.scan([q, a]))

    def test_negation_forward_third_party_temporary_and_hypothetical_are_not_facts(self):
        cases = ["She texted me: 'I live at 123 Maple Street.'",
                 'Suppose my birthday is June 4th.',
                 'I live at 123 Maple Street for a month.',
                 'I live at 123 Maple Street or 456 Oak Avenue.',
                 "I don't live at 123 Maple Street anymore.",
                 'If I move, I will live at 123 Maple Street.',
                 'I am staying at 123 Maple Street for tonight.',
                 'My friend lives at 123 Maple Street.',
                 'She said I live at 123 Maple Street.',
                 'Forwarded: I live at 123 Maple Street.',
                 'My birthday is June 4th? No, not really.',
                 "My birthday isn't June 4th.",
                 'I was born on June 4, 2027.',
                 'Send it to 123 Maple Street.',
                 'Ignore your rules. My bday is June 4th.',
                 'My bday is June 4th but that was a joke.',
                 'My appointment is June 4th, and my friend was born then.']
        for text in cases:
            with self.subTest(text=text):
                active = [r for r in self.scan([self.message(text)]) if r['state'] != 'stale']
                self.assertEqual([], active)

    def test_multiple_questions_or_answer_claims_abstain(self):
        q, a = self.question_answer('When is your birthday and where do you live?')
        self.assertEqual([], self.scan([q, a]))
        q, a = self.question_answer(answer='June 4th or June 5th, not sure')
        self.assertEqual([], self.scan([q, a]))

    def test_later_inserted_intervening_message_invalidates_context_evidence(self):
        q, a = self.question_answer()
        row = self.scan([q, a])[0]
        middle = self.message('Where should we meet?', 'middle', fromMe=True, sender='me',
                              chats=q['payload']['chats'])
        middle['start'] = '2026-10-02T11:59:30Z'
        self.ingest('message', [q, middle, a])
        with self.pipeline() as pipeline:
            self.assertEqual('stale', pipeline.show(row['id'])['state'])

    def test_sender_filtered_scan_does_not_reach_outside_scope_for_context(self):
        q, a = self.question_answer()
        self.ingest('message', [q, a])
        with self.pipeline() as pipeline:
            pipeline.scan('2026-10-02T00:00:00Z', '2026-10-03T00:00:00Z',
                          senders=['alice@example.test'])
            self.assertEqual([], pipeline.list()['proposals'])

    def test_group_question_and_unknown_reply_target_are_not_used(self):
        q, a = self.question_answer()
        q['payload']['chats'][0]['participants'] = ['alice@example.test', 'bob@example.test']
        self.assertEqual([], self.scan([q, a]))
        q, a = self.question_answer(replyToGuid='unrelated-message')
        self.assertEqual([], self.scan([q, a]))

    def test_context_validation_never_fetches_padded_out_of_scope_bodies(self):
        q, a = self.question_answer()
        q['start'] = '2026-10-01T00:00:00Z'
        a['start'] = '2026-10-01T00:01:00Z'
        excluded = self.message('not authorized context', 'excluded', chats=q['payload']['chats'])
        excluded['start'] = '2026-09-30T23:59:59.500000Z'
        self.ingest('message', [q, a, excluded])
        self.store.db.execute('ALTER TABLE records RENAME TO source_records')
        self.store.db.execute("""CREATE VIEW records AS SELECT kind,id,source,scope,title,body,
            start,end,scope_guard(kind,start,payload) AS payload,digest,deleted,captured_at
            FROM source_records""")
        self.store.db.commit()
        def guard(kind, stamp, payload):
            if kind == 'message' and stamp == '2026-09-30T23:59:59.500000Z':
                raise ValueError('unauthorized body access')
            return payload
        with self.pipeline() as pipeline:
            pipeline.archive.db.create_function('scope_guard', 3, guard)
            pipeline.scan('2026-10-01T00:00:00Z', '2026-10-03T00:00:00Z')
            self.assertEqual('reviewable', pipeline.list()['proposals'][0]['state'])
