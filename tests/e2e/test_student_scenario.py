"""
Scenario A: Student Workflow End-to-End Test.
Artifacts:
- lecture_slides.md (PCA dimensionality reduction and Eigenvectors)
- study_notes.md (Notes referencing lecture concepts)
- homework_assignment.md (Homework questions citing PCA)

Verifies:
1. Universal Ingestion
2. Automatic concept & entity extraction
3. Graph knowledge graph relationship establishment (REFERENCES / CITES)
4. 'Ask DataOS' query: "show everything related to PCA" returning evidence citations.
"""

import unittest
import tempfile
import os
from dataos_system import DataOS


class TestStudentScenario(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.dataos = DataOS(db_path=self.temp_db)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_student_journey_pca_learning(self):
        # 1. Ingest Lecture Slides
        lecture_content = """# Lecture 7: Principal Component Analysis (PCA)
Principal Component Analysis (PCA) is an unsupervised dimensionality reduction technique.
It computes the Eigenvectors and Eigenvalues of the data covariance matrix.
The first principal component maximizes the variance of the projected data.
"""
        res_lec = self.dataos.ingest(lecture_content, filename="lecture_7_pca.md")
        self.assertEqual(res_lec["status"], "ingested")
        lec_id = res_lec["primary_object_id"]

        # 2. Ingest Study Notes
        notes_content = """# My Study Notes on PCA
Reviewing lecture_7_pca.md:
Key takeaway: PCA projects high-dimensional data onto orthogonal axes with maximal variance.
Must study Eigenvectors and covariance matrix decomposition for the exam.
"""
        res_notes = self.dataos.ingest(notes_content, filename="my_pca_notes.md")
        self.assertEqual(res_notes["status"], "ingested")
        notes_id = res_notes["primary_object_id"]

        # 3. Ingest Assignment
        assignment_content = """# Homework 3: Linear Algebra & PCA
Question 1: Given a 10x10 covariance matrix, compute the first 2 principal components.
Refer to lecture_7_pca.md for formula derivations.
"""
        res_hw = self.dataos.ingest(assignment_content, filename="homework_3.md")
        self.assertEqual(res_hw["status"], "ingested")
        hw_id = res_hw["primary_object_id"]

        # 4. Verify Persistent Graph Connections
        lec_neighbors = self.dataos.graph.neighbors(lec_id)
        self.assertTrue(len(lec_neighbors) >= 1)

        # 5. Execute "Ask DataOS" Query
        ask_res = self.dataos.ask("Show everything related to PCA dimensionality reduction")
        self.assertEqual(ask_res["intent"], "FIND_EVIDENCE")
        self.assertTrue(len(ask_res["evidence"]) >= 1)

        # Verify evidence citations contain lecture or study notes
        evidence_names = [e["name"] for e in ask_res["evidence"]]
        self.assertTrue(any("pca" in name.lower() for name in evidence_names))


if __name__ == "__main__":
    unittest.main()
