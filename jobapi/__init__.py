"""The accounts API: Google sign-in and each job seeker's answers and saved roles.

Runs as one AWS Lambda behind CloudFront at /api. `app.handle` is plain Python, so the same
code runs in tests, in the local dev server and in Lambda.
"""
