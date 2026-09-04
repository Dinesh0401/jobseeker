# Skill: Spec-Driven Milestones

## Execution Discipline
1. **Spec First, Code Second**: No application code or database migrations may be written until `Technical_Specification.md` is approved.
2. **Milestone Scoping**: Work exclusively within the active milestone. Do not scaffold downstream modules until upstream contracts pass validation.
   - **Milestone 1**: `.agents/` + `Technical_Specification.md`
   - **Milestone 2**: `schema.sql` + `src/db/` + `src/evaluators/extraction.py` + unit tests
   - **Milestone 3**: `supabase/functions/telegram-webhook/` + callback verification
   - **Milestone 4**: Collectors + Gemini matcher + CV builder + Dispatcher + Workflows
3. **Approval Gate**: Stop and require explicit user review at the end of every phase before advancing personas.
