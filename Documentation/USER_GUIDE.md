# SOP Migration System — User Guide

This guide explains how to use the SOP Migration & Content Extraction System web application to upload, review, and migrate Standard Operating Procedures (SOPs). It is written for reviewers, document owners, and administrators — no programming knowledge required.

> Looking for developer/technical documentation instead? See [`TECHNICAL_ARCHITECTURE.md`](./TECHNICAL_ARCHITECTURE.md).

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [Getting Started](#2-getting-started)
3. [The SOP Repository (Home Page)](#3-the-sop-repository-home-page)
4. [Uploading Documents](#4-uploading-documents)
5. [Tracking Extraction Progress](#5-tracking-extraction-progress)
6. [Viewing Extracted Content](#6-viewing-extracted-content)
7. [The Review Workspace](#7-the-review-workspace)
8. [Migrating a Document to a New Template](#8-migrating-a-document-to-a-new-template)
9. [Reprocessing Requests (Admin)](#9-reprocessing-requests-admin)
10. [Managing Your Account](#10-managing-your-account)
11. [Troubleshooting & FAQ](#11-troubleshooting--faq)
12. [Glossary](#12-glossary)

---

## 1. What This System Does

The SOP Migration System takes existing Standard Operating Procedure documents (PDF or Word/.docx) and:

1. **Extracts** their full structure — headings, paragraphs, lists, tables, images, icons, and captions — while preserving reading order, even for documents with icon rails, multi-column layouts, and tables that span multiple pages.
2. **Organizes** that content into a structured, hierarchical representation (sections → paragraphs/lists/tables/images) that can be inspected, reviewed, and reused.
3. **Migrates** the extracted content into a new corporate DOCX template automatically, using AI to intelligently map old sections into the new template's structure, rebuild tables, callout boxes, and a Table of Contents, and produce a Quality Assurance (QA) report.

Everything happens inside a single web application with three main areas:

| Area | Purpose |
|---|---|
| **SOP Repository** | Upload documents and browse everything that has been processed. |
| **SOP Content View** | Read the extracted structure of a single document as clean, formatted content. |
| **Review Workspace** | Compare original vs. extracted/migrated/translated content, leave comments, and approve. |

---

## 2. Getting Started

### 2.1 Signing Up

1. Navigate to the application (default: `http://localhost:5173`).
2. If you don't have an account, click **Sign Up**.
3. Fill in your details:
   - First name, last name
   - Company (BI) email address
   - Password (minimum 12 characters; cannot be the same as your email)
   - Confirm password
   - A **secret question** and answer (used for account recovery)
4. Submit the form. Your account is created with the default **Regular User** role and you are automatically signed in.

### 2.2 Logging In

1. Go to the **Login** page.
2. Enter your BI email and password.
3. Optionally check **Remember Me** to stay signed in for longer (30 days instead of 1 day) via a secure, HttpOnly refresh cookie.
4. On success you're redirected to the SOP Repository.

Notes on account security:
- After **5 failed login attempts**, the account is temporarily locked for 15 minutes.
- Repeated login attempts from the same network address are also rate-limited.
- Sessions are automatically refreshed in the background while you use the app — you generally won't be asked to log in again mid-session unless your refresh session has fully expired or you explicitly log out.

### 2.3 Logging Out

Use the **Logout** option in the header/sidebar. This revokes your session on the server and clears your browser session — you'll be redirected to the Login page.

### 2.4 Staying Signed In Across Tabs/Restarts

When you reload the app, it silently attempts to refresh your session using the secure cookie set at login. If that succeeds, you're returned to where you were without re-entering credentials. If it fails (session expired, logged out elsewhere, etc.), you're sent to the Login page.

---

## 3. The SOP Repository (Home Page)

This is the landing page after login and the central hub for all documents.

### What you'll see

- **Stat cards** — quick counts (e.g., total SOPs, in review, approved, rejected).
- **Search bar** — search by title, document name, document number, document UID, or original filename.
- **Filter bar** — filter by review **status** (`in_review`, `approved`, `rejected`) and by **file type** (PDF / DOCX).
- **View toggle** — switch between a **Table** view (dense, sortable list) and a **Grid** (card) view.
- **Upload** button — opens the upload dialog (see [Section 4](#4-uploading-documents)).
- **Job progress banner** — appears automatically while a batch upload/extraction is running, and disappears (with a success toast) once complete.

### Each SOP record shows

| Field | Meaning |
|---|---|
| Title / Document Name | Extracted from the SOP's cover page/preamble |
| Document Number | Extracted SOP identifier (e.g., `BI-VQD-09748`) |
| Version | Document version parsed from the source file |
| File Type | `pdf` or `docx` |
| Status | `in_review`, `approved`, or `rejected` |
| Upload/Extraction Version | Internal re-upload counter — re-uploading the same document creates a new version rather than overwriting history |
| Created / Updated timestamps | When the record was first extracted and last touched |

### Actions available per record

- **Open** — go to the [SOP Content View](#6-viewing-extracted-content) to read the extracted document.
- **Review** — open the [Review Workspace](#7-the-review-workspace) for that document.
- **Change status** — mark a record `approved` or `rejected` directly (also available from the Content View page).
- **Delete** — removes the SOP record from the repository **and** performs smart cleanup of its files on disk (uploaded source file, extracted images/icons, and generated JSON).

---

## 4. Uploading Documents

1. Click **Upload** on the SOP Repository page.
2. Select one or more **PDF** or **DOCX** files (drag-and-drop or file picker).
   - Maximum file size: **50 MB** per file (configurable by the administrator).
   - Only `.pdf` and `.docx` extensions are accepted; anything else is rejected.
3. Confirm the upload. This submits a **batch job**.
4. The system will:
   - Save each file to the server.
   - Automatically read the first page/preamble table of each document to determine its **Title**, **Document Name**, **Document Number**, and **Version** — this becomes the document's stable **UID** used everywhere else in the app.
   - Detect if a document with the same UID was already uploaded before; if so, it is treated as a **new version** (the version counter increments) rather than a duplicate.
   - Queue each document for background extraction.

You do not need to wait on this page — extraction happens in the background and you'll see live progress (see next section).

> **Tip:** If a file is rejected during a batch upload (wrong extension, empty, or too large), it is silently skipped from that batch; only valid files are queued.

---

## 5. Tracking Extraction Progress

After uploading, a **Job Progress Banner** appears at the top of the SOP Repository showing:

- Overall batch percentage complete.
- Per-document status: `queued` → `processing` → `completed` / `failed`.
- A human-readable message for the current pipeline stage (e.g., "Parsing document...", "Running extraction pipeline...", "Building Abstract Syntax Tree...", "Generating hierarchical and semantic chunks...", "Finalizing output...").

Internally, each document passes through six stages:

1. **Parse** — read raw text, images, and layout from the PDF/DOCX.
2. **Tables** — detect tables, clean up messy grids, and stitch tables that continue across multiple pages.
3. **Icons** — extract and classify inline icons (safety, informational, navigation, etc.) and captions.
4. **AST Build** — assemble everything into a structured document tree (sections, headings, paragraphs, lists, tables, images).
5. **Chunking** — split the tree into review-friendly and retrieval-friendly chunks.
6. **Export** — write the final structured JSON and register the SOP in the repository.

If a document fails, its status becomes `failed` and a short, safe error message is shown (e.g., "Extraction failed") — the underlying technical error is recorded in the system logs for administrators, not exposed to end users.

The progress banner polls automatically and disappears with a success notification once the whole batch finishes; the repository list refreshes to show the new/updated records.

---

## 6. Viewing Extracted Content

Click any SOP record to open its **Content View** page. This renders the extracted document the way it would read in the original SOP, including:

- **Section navigation** — a sidebar listing all detected sections/headings; click to jump directly to that section.
- **Headings, paragraphs, and lists** — rendered with their original nesting and numbering.
- **Icons** — shown to the left of the paragraph they annotate, matching the original SOP's "icon rail" layout (e.g., a target icon next to the Purpose statement, a globe icon next to a "Worldwide" applicability bullet).
- **Tables** — rendered as real tables, including merged cells, header rows, and cell-level icons/images where present.
- **Images and figures** — inline, with captions where detected.
- **Highlighted text** — original highlight colors are preserved where the source document used them.

You can also change the document's **review status** (`in_review` / `approved` / `rejected`) from this page.

If a single element fails to render (e.g., an unusually shaped table), only that element shows an error placeholder — the rest of the page continues to display normally.

---

## 7. The Review Workspace

Open **Review** on a document to enter the Review Workspace — a dedicated, side-by-side comparison and sign-off tool. The workspace supports **three modes**, switchable from the same page:

### 7.1 Extraction Review Mode (default)

- **Left panel:** the original document (PDF/DOCX viewer).
- **Right panel:** the extracted content (same renderer as the Content View).
- **Compare view** to visually align original vs. extracted content.
- **AI Suggestion Panel** — proposed corrections (e.g., title casing fixes) that you can **Accept** or **Reject**.
- **Issue Panel** — log content problems you find (category, description, expected value) for follow-up.
- Available actions: **Edit**, **Save**, **Report Issue**, **Request Reprocessing**, **Resolve Warning**, **Approve**.
- **Request Reprocessing** opens a dialog where you describe what needs to be re-extracted (e.g., "table on page 4 needs review") and optionally which pages — this creates a request an administrator can approve to re-run extraction.

### 7.2 Migration Review Mode

- **Left panel:** current/source format. **Right panel:** migrated (new template) format.
- **Migration Validation Panel** — shows the automated QA report: content coverage %, sections mapped, low-confidence warnings, and validation errors.
- Available actions: **AI Migrate**, **Accept Suggestion**, **Edit**, **Apply Template**, **Validate**, **Save**, **Render Preview**, **Approve**.
- This is where you trigger and review a [template migration](#8-migrating-a-document-to-a-new-template).

### 7.3 Translation Review Mode

- **Left panel:** source content. **Right panel:** translated content.
- **Translation QA Panel** and **Glossary Panel** to check terminology consistency.
- Available actions: **AI Translate**, **Accept Suggestion**, **Edit**, **Save**, **Run QA**, **Approve**.

### Common to all modes

- **Version History** — see prior versions/revisions of the workflow.
- **Action Footer** — primary actions for the current mode (Save / Approve / etc.) plus a running status indicator.
- Switching modes preserves your place in the document where possible; the URL keeps track of the mode (`?mode=review|migration|translation`) so you can share or bookmark a specific view.

---

## 8. Migrating a Document to a New Template

Once a document has been extracted, you can migrate its content into a standardized corporate DOCX template.

### How to run it

1. Open the document's **Review Workspace** and switch to **Migration** mode (or use the migration action from the Content View, depending on your role).
2. Optionally upload a **custom template** (.docx). If you don't provide one, the system uses the default template configured by your administrator (`data/templates/`).
3. Trigger **Apply Template / AI Migrate**.

### What happens behind the scenes

The system runs a 5-phase migration:

1. **Template Inspection** — the target template is scanned to understand its section headings, tables (including placeholder tables like "Document History"), fonts, and instructional/example text.
2. **Content Summarization** — the extracted SOP's sections are summarized for the AI planner (either a fast rule-based summary, or a deeper AI-generated semantic summary, depending on configuration).
3. **AI Migration Planning** — an AI model produces a detailed plan mapping every source section, paragraph, list, table, and image to a specific place in the new template — including how to style callout boxes, which tables to populate vs. delete, and where to insert content that doesn't have an obvious home in the template.
4. **Document Assembly** — the plan is executed: headings, paragraphs, lists, tables, images, and callout boxes are inserted into a copy of the template; leftover template placeholder/instructional text is cleaned up; a Table of Contents field is inserted.
5. **Automated QA** — the final document is validated and a report is produced covering content coverage percentage, how many sections/elements were placed vs. skipped, any low-confidence warnings, and outstanding validation errors.

### After migration completes

- **Download** the finished `.docx` directly from the Review Workspace.
- Review the **Migration Plan** (what was mapped where) and the **QA Report** (coverage, warnings, errors) before approving.
- If the QA report shows `needs_review`, check the flagged warnings — these usually indicate a section the AI wasn't fully confident about, or content that didn't map cleanly into the template.

---

## 9. Reprocessing Requests (Admin)

Reviewers can submit a **Reprocessing Request** from the Extraction Review mode when they spot a systematic extraction problem (e.g., a misread table). Administrators manage these from the **Reprocessing Admin** page:

- View all requests, filterable by status: `pending_approval`, `approved`, `rejected`.
- **Approve** or **Reject** (with a required decision comment) a request.
- Each request shows who requested it, when, the stated reason, and (optionally) which pages are affected.

> **Current state:** in this version, approving/rejecting a request records the decision in the admin view; automatically re-queuing an approved request for extraction is planned but not yet wired end-to-end — treat an approval today as a signal to a team member to manually trigger re-extraction if needed.

---

## 10. Managing Your Account

- Your profile (name, email, role, status) is available via the **/me** endpoint the app uses to populate the header/profile menu.
- Roles determine what you can do in the system (e.g., regular reviewer vs. administrator functionality like Reprocessing Admin).
- If your account is disabled or your role is deactivated by an administrator, you'll be signed out and blocked from logging in again until it's restored.

---

## 11. Troubleshooting & FAQ

**Q: My upload was rejected immediately.**
A: Check the file extension (`.pdf` or `.docx` only), that the file isn't empty, and that it's under the configured size limit (default 50 MB).

**Q: My document shows "failed" after extraction.**
A: The source file may be corrupted, password-protected, or in an unsupported format. Contact your administrator — the detailed error is captured in the system logs (with a correlation ID) for troubleshooting, without exposing internal details to you.

**Q: I re-uploaded the same SOP and now see two entries.**
A: This is expected — re-uploading a document creates a new **version** of the same document UID rather than silently overwriting the previous extraction, so review history isn't lost. The Content View and migration always use the latest extracted JSON for that document.

**Q: An icon or image looks misplaced in the preview.**
A: Use **Report Issue** or **Request Reprocessing** in the Extraction Review mode to flag it; this feeds back into the extraction quality-improvement backlog.

**Q: The Migration QA report says "needs_review".**
A: Open the **Migration Validation Panel** to see specific warnings (e.g., low-confidence section mapping) — these need human review before you approve the migrated document.

**Q: I got logged out unexpectedly.**
A: Your session (or the "Remember Me" window) expired, or you were signed out from another device/session revocation event. Simply log in again.

**Q: Every API error I see has a "correlation ID" — what's that for?**
A: It's a support reference number. If you report a problem, share this ID (shown in the error message/metadata) so an administrator can find the exact matching entries in the system's logs.

---

## 12. Glossary

| Term | Meaning |
|---|---|
| **SOP** | Standard Operating Procedure — the source document type this system processes. |
| **Document UID** | A stable identifier generated from a document's name/number/version, used to track versions of the same SOP over time. |
| **AST (Abstract Syntax Tree)** | The structured, hierarchical representation of a document's content (sections, headings, paragraphs, tables, images, icons) produced by the extraction pipeline. |
| **Chunk** | A retrieval/review-sized slice of the AST, produced by hierarchical and semantic chunking. |
| **Extraction** | The process of turning a raw PDF/DOCX into structured content (parsing, table/icon detection, AST building). |
| **Migration** | The process of placing extracted content into a new DOCX template using AI-assisted planning. |
| **Migration Plan** | The AI-generated blueprint describing exactly where each piece of source content goes in the new template. |
| **QA Report** | The automated post-migration quality report (coverage %, warnings, errors). |
| **Batch Job** | A group of documents uploaded together and processed as a unit; you can track its combined progress. |
| **Correlation ID** | A unique ID attached to a request/job used to trace it through the system's logs for support purposes. |
| **Review Workspace** | The side-by-side comparison and approval UI, supporting Extraction, Migration, and Translation modes. |
| **Reprocessing Request** | A reviewer-submitted request to re-run extraction on a document, subject to admin approval. |
