-- A tool call that logs a session can run again (an interrupted sibling call resumes the
-- whole tool step), so each tool call writes at most one session.
alter table sessions add column source_call_id text;
create unique index sessions_one_per_tool_call on sessions (athlete_id, source_call_id)
  where source_call_id is not null;
