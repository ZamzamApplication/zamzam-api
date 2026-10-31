# Public student registration

Managers open **التسجيل العام** on web (`/registration`) or **المزيد → التسجيل العام وطلبات الطلاب** on mobile.

1. Create custom student fields (text, number, date, yes/no, or select).
2. Create a registration form and select which custom fields students fill in. Unselected fields remain internal and are completed by the manager when approving. Required internal fields still block final enrollment until completed.
3. Share the form link or QR. The public form is responsive and requires no account. Open the printable A4 poster and use Print / Save as PDF. Mobile opens this same printable page in the browser.
4. Pending counts appear in the manager's app navigation, refreshed every 30 seconds while open. These are in-app notifications; no OS push provider is required.
5. Choose Accept to open the completion dialog. Edit the student details, assign a sheikh (or leave unassigned), complete the internal fields, and confirm. Only this final confirmation creates the student. Rejecting creates no student.

Forms can be edited, closed and reopened without changing their QR. Closing a form also disables its public poster. Requests preserve their original field labels and answers even after fields are renamed or archived. Review history is available with the approved/rejected filters. Enrollment and decision are committed together; repeated or simultaneous approvals cannot add a second student. Existing student subscription and custom field rules apply.

## Configuration and migration

Set `PUBLIC_WEB_URL` on the API to the public HTTPS web origin, e.g. `https://zamzam-web.fly.dev` (the default). Mobile QR and sharing use this value. For a local environment set it to a web address reachable by the test phone. Web sharing and poster QR use the current web origin.

The Alembic revision `20261031_34` adds two tables without changing existing student records. Run `alembic upgrade head` as part of the usual release process. Do not deploy from a dirty checkout. Both clients and the API must be released for the feature to work end to end.

Public form preview exposes only selected active fields. Submission validates typed values, limits attempts per IP and uses a honeypot. Management routes require tenant admin and scope every lookup and decision to the active Tahfiz. No API endpoint sends public applicants the manager's internal fields or pending applications.
