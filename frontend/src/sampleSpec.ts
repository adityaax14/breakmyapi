export const SAMPLE_SPEC = `openapi: 3.0.3
info:
  title: Notes API
  version: 1.0.0
security:
  - bearerAuth: []
paths:
  /login:
    post:
      security: []
      requestBody: {}
  /notes:
    get: {}
  /notes/{note_id}:
    get: {}
    patch:
      requestBody: {}
  /admin/users:
    get:
      tags: [admin]
`;
