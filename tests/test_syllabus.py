"""The syllabus Somo grounds on.

Two properties matter more than the rest. First, that a student naming their
subject and form in ordinary language — in either language — is understood,
because nothing else works until that is settled. Second, that what reaches
the prompt is what TIE actually wrote: the whole point of grounding is that
the tutor can be held to a text, so anything invented here would be worse
than no syllabus at all.
"""

import json
import unittest

import bots
from core import syllabus


class DataTests(unittest.TestCase):
    def test_the_syllabus_is_present(self):
        self.assertGreaterEqual(len(syllabus.subjects()), 14)

    def test_the_core_science_and_language_subjects_are_there(self):
        have = set(syllabus.subjects())
        for expected in ("Biology", "Chemistry", "Physics", "Mathematics",
                         "Kiswahili", "English Language"):
            self.assertIn(expected, have)

    def test_forms_come_back_in_school_order(self):
        self.assertEqual(syllabus.forms_for("Biology"), list(syllabus.FORMS))

    def test_a_subject_only_taught_in_the_upper_forms_says_so(self):
        """Literature in English starts in Form Three in the Tanzanian
        system, and the data reflects that. A tutor claiming a Form One
        Literature syllabus would be inventing one."""
        self.assertEqual(syllabus.forms_for("Literature in English"),
                         ["Form Three", "Form Four"])

    def test_every_row_carries_its_competence(self):
        """The competence is what a student is assessed against, so it is the
        one field that must never be missing."""
        for subject in syllabus.subjects():
            for form in syllabus.forms_for(subject):
                for row in syllabus.activities(subject, form):
                    self.assertTrue(row["main"].strip(), (subject, form))
                    self.assertTrue(row["competence"].strip(), (subject, form))

    def test_a_missing_learning_activity_leaves_no_hole_in_the_prompt(self):
        """22 of 769 activities didn't survive TIE's PDFs. The competence
        above them is intact, so the row still carries — but it must not
        render as a blank line, which would read as a gap in the syllabus
        rather than a gap in the parse."""
        text = syllabus.context("Chemistry", "Form Two")
        self.assertNotIn("\n      \n", text)
        for line in text.splitlines():
            self.assertTrue(line == "" or line.strip(), repr(line))


class DetectTests(unittest.TestCase):
    def test_subject_and_form_together(self):
        self.assertEqual(syllabus.detect("im doing form two biology"),
                         ("Biology", "Form Two"))

    def test_swahili(self):
        self.assertEqual(syllabus.detect("kidato cha nne, fizikia"),
                         ("Physics", "Form Four"))
        self.assertEqual(syllabus.detect("naomba msaada wa hisabati kidato cha kwanza"),
                         ("Mathematics", "Form One"))

    def test_mixed_languages_in_one_sentence(self):
        """Students switch mid-sentence constantly; so must the matching."""
        self.assertEqual(syllabus.detect("nataka help na chemistry form 3"),
                         ("Chemistry", "Form Three"))

    def test_short_forms(self):
        self.assertEqual(syllabus.detect("F1 maths"), ("Mathematics", "Form One"))
        self.assertEqual(syllabus.detect("form iv geography"),
                         ("Geography", "Form Four"))

    def test_longest_subject_match_wins(self):
        """'literature in english' must not be captured by 'english'."""
        self.assertEqual(syllabus.find_subject("literature in english"),
                         "Literature in English")
        self.assertEqual(syllabus.find_subject("english language"),
                         "English Language")

    def test_half_an_answer_is_still_an_answer(self):
        self.assertEqual(syllabus.detect("im in form two"), (None, "Form Two"))
        self.assertEqual(syllabus.detect("biology please"), ("Biology", None))

    def test_nothing_named(self):
        self.assertEqual(syllabus.detect("i need help with my homework"),
                         (None, None))
        self.assertEqual(syllabus.detect(""), (None, None))

    def test_a_form_number_inside_a_bigger_number_is_not_a_form(self):
        self.assertIsNone(syllabus.find_form("question 14 on page 231"))

    def test_punctuation_and_case_do_not_matter(self):
        self.assertEqual(syllabus.detect("FORM 2 — Biology!"),
                         ("Biology", "Form Two"))


class ContextTests(unittest.TestCase):
    def test_with_nothing_settled_it_offers_the_catalogue(self):
        """This is what lets the tutor ask a precise opening question."""
        text = syllabus.context(None, None)
        self.assertIn("Biology", text)
        self.assertIn("Form One to Form Four", text)

    def test_a_settled_pair_brings_the_competences(self):
        text = syllabus.context("Biology", "Form Two")
        self.assertIn("Biology, Form Two", text)
        self.assertIn("Tanzania Institute of Education", text)
        rows = syllabus.activities("Biology", "Form Two")
        self.assertIn(rows[0]["competence"], text)
        self.assertIn(rows[0]["activity"], text)

    def test_the_context_tells_it_not_to_stray(self):
        text = syllabus.context("Biology", "Form Two")
        self.assertIn("isn't in this form's syllabus", text)

    def test_every_line_of_the_injection_comes_from_the_data(self):
        """Nothing invented: each indented line must be a real syllabus
        string. This is the property the whole feature rests on."""
        subject, form = "Chemistry", "Form Three"
        rows = syllabus.activities(subject, form)
        allowed = set()
        for row in rows:
            allowed |= {row["main"], row["competence"], row["activity"]}
        body = syllabus.context(subject, form)
        indented = [ln.strip() for ln in body.splitlines()
                    if ln.startswith("  ") and ln.strip()]
        self.assertTrue(indented)
        for line in indented:
            self.assertIn(line, allowed)

    def test_a_form_with_no_data_is_admitted_not_invented(self):
        text = syllabus.context("Biology", "Form Nine")
        self.assertIn("no syllabus data", text)

    def test_an_unknown_subject_is_admitted_not_invented(self):
        text = syllabus.context("Astrophysics", "Form Two")
        self.assertIn("no syllabus data", text)

    def test_the_injection_stays_small_enough_for_a_prompt(self):
        """The whole syllabus is ~206k characters. One form must stay in the
        low thousands or it crowds out the conversation itself."""
        for subject in syllabus.subjects():
            for form in syllabus.FORMS:
                size = len(syllabus.context(subject, form))
                self.assertLess(size, 12000, f"{subject} {form}: {size}")


class BotTests(unittest.TestCase):
    def test_somo_is_registered(self):
        self.assertIsNotNone(bots.get("somo"))

    def test_somo_has_the_syllabus_feature_and_the_others_do_not(self):
        self.assertTrue(bots.get("somo").has("syllabus"))
        self.assertFalse(bots.get("lissa").has("syllabus"))
        self.assertFalse(bots.get("athar").has("syllabus"))

    def test_somo_does_not_claim_prayer(self):
        self.assertFalse(bots.get("somo").has("prayer"))

    def test_its_manifest_is_serialisable(self):
        """The page is dressed from this; anything unserialisable is a blank
        screen rather than a degraded one."""
        json.dumps(bots.get("somo").manifest(), ensure_ascii=False)

    def test_it_speaks_the_languages_its_students_write_in(self):
        self.assertEqual(set(bots.get("somo").langs), {"en", "sw"})

    def test_the_teaching_instruction_survives_into_the_prompt(self):
        """The whole persona is 'ask, don't tell' — if that ever falls out of
        the system prompt, Somo is just another answer machine."""
        prompt = bots.get("somo").system_prompt
        self.assertIn("teach by asking", prompt)
        self.assertIn("ONE question at a time", prompt)
        self.assertIn("do not do it for them", prompt.lower())


if __name__ == "__main__":
    unittest.main()
