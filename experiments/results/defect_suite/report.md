# Defect suite report

Run 2026-11-18T14:59:50+00:00, mode local_test. Synthetic input made to provoke errors; a result here is a place to look.

## Part 1: broken files

28 files, 0 with an unexpected outcome. Server healthy afterwards: yes. Stored names that leave the upload folder: 0.

| Case | File | Outcome | Detail | Problem |
|---|---|---|---|---|
| F01 empty file | `empty.txt` | refused with a reason (422, 0.0 s) | File is empty. |  |
| F02 only spaces and line breaks | `blank.txt` | refused with a reason (422, 0.0 s) | Empty or binary text document. |  |
| F03 random bytes named .pdf | `random.pdf` | refused with a reason (422, 0.0 s) | File content does not match declared type '.pdf'. Upload was rejected for security reasons. |  |
| F04 PDF header followed by garbage | `truncated.pdf` | refused with a reason (201, 0.4 s) | The file could not be read as PDF. It may be damaged or incomplete; export or save it again and upload the new |  |
| F05 valid PDF with one blank page (like a scan) | `scan.pdf` | refused with a reason (201, 0.4 s) | No extractable text. For scanned PDFs, install Tesseract or upload a text/OCR version. |  |
| F06 zip archive named .docx | `notes.docx` | refused with a reason (422, 0.0 s) | Invalid Office document structure. |  |
| F07 Word document with no text | `empty.docx` | refused with a reason (201, 0.4 s) | The document contains no text. |  |
| F08 valid Word document with German text | `Übung.docx` | processed (201, 0.7 s) | 1 passage(s) |  |
| F09 text saved as Latin-1 with umlauts | `latin1.txt` | refused with a reason (422, 0.0 s) | Text documents must be UTF-8 encoded. |  |
| F10 text saved as UTF-16 | `utf16.txt` | refused with a reason (422, 0.0 s) | Text documents must be UTF-8 encoded. |  |
| F11 text with a byte-order mark (as Notepad saves it) | `bom.txt` | processed (201, 0.7 s) | 1 passage(s) |  |
| F12 text containing zero bytes | `nul.txt` | refused with a reason (422, 0.0 s) | Empty or binary text document. |  |
| F13 program file | `tool.exe` | refused with a reason (422, 0.0 s) | File type '.exe' is not allowed. Accepted: pdf, docx, pptx, txt, md, vtt |  |
| F14 double extension | `lecture.pdf.exe` | refused with a reason (422, 0.0 s) | File type '.exe' is not allowed. Accepted: pdf, docx, pptx, txt, md, vtt |  |
| F15 no extension | `lecture` | refused with a reason (422, 0.0 s) | File has no extension. |  |
| F16 file name that tries to leave the upload folder | `../../outside.txt` | processed (201, 0.7 s) | 1 passage(s) |  |
| F17 file name with umlauts, spaces and a dash | `Vorlesung Übung – 01.txt` | processed (201, 0.7 s) | 1 passage(s) |  |
| F18 file name of 300 characters | `aaaaaaaaaaaaaaaaaaaa…aaaa.txt` | processed (201, 0.7 s) | 1 passage(s) |  |
| F19 one 2 MB line without any space | `oneline.txt` | refused with a reason (201, 0.7 s) | The document contains no readable text: fewer than 3 different words were found. |  |
| F20 transcript without timestamps | `plain.vtt` | refused with a reason (201, 0.4 s) | No spoken text was found. A transcript needs cue lines such as "00:00:01.000 --> 00:00:05.000", each followed  |  |
| F21 transcript with a broken timestamp line | `broken.vtt` | refused with a reason (201, 0.4 s) | No spoken text was found. A transcript needs cue lines such as "00:00:01.000 --> 00:00:05.000", each followed  |  |
| F22 valid transcript | `good.vtt` | processed (201, 0.7 s) | 1 passage(s) |  |
| F23 Markdown with headings only | `headings.md` | processed (201, 0.7 s) | 3 passage(s) |  |
| F24 only digits and symbols | `symbols.txt` | refused with a reason (201, 0.7 s) | The document contains no readable text: fewer than 3 different words were found. |  |
| F25 text file declared as PDF by the browser | `declared.txt` | refused with a reason (422, 0.0 s) | MIME type does not match the file extension. |  |
| F26 unknown document type chosen | `kind.txt` | refused with a reason (422, 0.0 s) | artifact_type must be one of: syllabus, slides, assignment, transcript, module_manual, other, exam, assessment |  |
| F27 script tags and SQL in the text | `inject.txt` | processed (201, 0.7 s) | 1 passage(s) |  |
| F28 the same file a second time | `bom.txt` | refused with a reason (409, 0.0 s) | This file was already uploaded (artifact id: b8411a82-31ad-4eb2-a31a-066d684213d4). |  |

## Part 2: planted misalignments

### en_clean

Run: completed. Findings: 0. No defect planted: every finding is a possible false alarm.

Scores: content assessment 84%, content delivery 100%, metadata assessment 100%, metadata content 76%.

Objectives the system extracted: EXT-1 [understand] explain how insertion sort and merge sort order a list of numbers; EXT-2 [analyse] analyse the running time of binary search on a sorted array; EXT-3 [evaluate] evaluate chaining and open addressing for collisions in hash tables.

### en_defects

Run: waiting_for_human. Findings: 11. Planted defects found: 8 of 8.

Scores: content assessment 58%, content delivery 80%, metadata assessment 40%, metadata content 59%.

| Planted defect | Dimension | Found | By finding type | Seen in other dimensions |
|---|---|---|---|---|
| EN-1 objective on dynamic programming is stated but never taught | metadata content | yes | clo_not_covered | content assessment, content delivery, metadata assessment |
| EN-2 red-black trees are taught but not in the module manual | metadata content | yes | taught_topic_outside_metadata |  |
| EN-3 exam question on network flow, a topic never taught | content assessment | yes | assessment_weak_support |  |
| EN-4 hash-table objective says evaluate, the exam only asks to define and name | metadata assessment | yes | assessment_level_below_objective | content delivery |
| EN-5 breadth-first search objective is never assessed | metadata assessment | yes | clo_not_assessed |  |
| EN-6 dynamic programming objective is never assessed | metadata assessment | yes | clo_not_assessed | content assessment, content delivery, metadata content |
| EN-7 hash tables are on the slides but skipped in the lecture | content delivery | yes | delivery_not_covered | metadata assessment |
| EN-8 lecture digression on quantum computing that is on no slide | content delivery | yes | delivery_unplanned |  |

Findings that match no planted defect (3):

- content assessment / topic_not_assessed (warning): Topic 'Graph traversal' has lecture content but no assessment questions.
- content assessment / topic_not_assessed (warning): Topic 'Dynamic programming' has lecture content but no assessment questions.
- content delivery / topic_not_delivered (warning): Week 5 topic 'Dynamic programming' has no corresponding slides or transcript content.

Objectives the system extracted: EXT-1 [understand] explain how insertion sort and merge sort order a list of numbers; EXT-2 [analyse] analyse the running time of binary search on a sorted array; EXT-3 [evaluate] evaluate chaining and open addressing for collisions in hash tables; EXT-4 [apply] apply breadth-first search to traverse a graph; EXT-5 [create] design dynamic programming solutions for optimisation problems such as.

### de_defects

Run: waiting_for_human. Findings: 9. Planted defects found: 5 of 5.

Scores: content assessment 44%, content delivery 61%, metadata assessment 50%, metadata content 55%.

| Planted defect | Dimension | Found | By finding type | Seen in other dimensions |
|---|---|---|---|---|
| DE-1 Lernziel zur dynamischen Programmierung wird nicht gelehrt | metadata content | yes | clo_not_covered | content assessment, content delivery, metadata assessment |
| DE-2 Rot-Schwarz-Bäume werden gelehrt, stehen aber nicht im Modulhandbuch | metadata content | yes | taught_topic_outside_metadata |  |
| DE-3 Klausuraufgabe zum maximalen Fluss, der nie gelehrt wird | content assessment | yes | assessment_weak_support |  |
| DE-4 Lernziel Tiefensuche wird nicht geprüft | metadata assessment | yes | clo_not_assessed | content assessment |
| DE-5 Lernziel dynamische Programmierung wird nicht geprüft | metadata assessment | yes | clo_not_assessed | content assessment, content delivery, metadata content |

Findings that match no planted defect (3):

- content assessment / topic_not_assessed (warning): Topic 'Graphen und Tiefensuche' has lecture content but no assessment questions.
- content assessment / topic_not_assessed (warning): Topic 'Dynamische Programmierung' has lecture content but no assessment questions.
- content delivery / topic_not_delivered (warning): Week 4 topic 'Dynamische Programmierung' has no corresponding slides or transcript content.

Objectives the system extracted: EXT-1 [understand] Die Studierenden können die binäre Suche in einem sortierten Array erk; EXT-2 [understand] Die Studierenden können Verkettung und offene Adressierung bei Kollisi; EXT-3 [apply] Die Studierenden können die Tiefensuche auf einen Graphen anwenden.; EXT-4 [create] Die Studierenden können Lösungen mit dynamischer Programmierung für da.
