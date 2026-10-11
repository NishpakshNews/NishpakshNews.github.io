-- "Talk to the article" (live voice conversation about one article; owner, Oct 11 2026).
-- Only the Edge Function `live-token` touches these (service role): it asks `live_talk_begin` before it hands a reader
-- a one-use Gemini token. One row = one conversation started. Limits live here, not in the browser:
--   * per reader per IST day (p_daily), like request_audio's one-a-day,
--   * site-wide at the same moment (p_concurrent), because the Live models are capped in tokens a minute, not in requests.
-- The row's age says whether the conversation can still be running (p_seconds = the longest one allowed), so the
-- browser never has to report that a conversation ended.

create table if not exists public.live_sessions (
  id bigserial primary key,
  reader uuid not null references auth.users on delete cascade,
  story_id integer not null,
  lang varchar(4) not null,
  started_at timestamptz not null default now()
);
create index if not exists live_sessions_reader_day on public.live_sessions (reader, started_at);
create index if not exists live_sessions_started on public.live_sessions (started_at);

alter table public.live_sessions enable row level security;
-- Supabase grants new public tables to anon and authenticated: a reader has no business here.
revoke all on public.live_sessions from anon, authenticated;
revoke all on sequence public.live_sessions_id_seq from anon, authenticated;
grant select, delete on public.live_sessions to nishpaksh_app;       -- the pipeline may count or clean up
create policy app_full_access on public.live_sessions for all to nishpaksh_app using (true) with check (true);

-- begin: 'ok' (id, n = this IST day's conversations so far, used to spread them over the keys) | 'login' | 'bad' |
-- 'gone' (the article is not live) | 'limit' (this reader's day is used) | 'busy' (the site is at its limit right now)
create or replace function public.live_talk_begin(
  p_reader uuid, p_story integer, p_lang text, p_daily integer, p_concurrent integer, p_seconds integer
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  today_start timestamptz := (date_trunc('day', now() at time zone 'Asia/Kolkata')) at time zone 'Asia/Kolkata';
  new_id bigint;
  n integer;
begin
  if p_reader is null then return jsonb_build_object('status', 'login'); end if;
  if p_lang not in ('en', 'hi') or p_daily < 1 or p_concurrent < 1 or p_seconds < 30 then
    return jsonb_build_object('status', 'bad');
  end if;
  if not exists (select 1 from published where story_id = p_story) then
    return jsonb_build_object('status', 'gone');
  end if;
  perform pg_advisory_xact_lock(7001);                 -- two readers starting at the same moment count each other
  if (select count(*) from live_sessions where reader = p_reader and started_at >= today_start) >= p_daily then
    return jsonb_build_object('status', 'limit');
  end if;
  if (select count(*) from live_sessions where started_at > now() - make_interval(secs => p_seconds)) >= p_concurrent then
    return jsonb_build_object('status', 'busy');
  end if;
  delete from live_sessions where started_at < now() - interval '14 days';
  insert into live_sessions (reader, story_id, lang) values (p_reader, p_story, p_lang) returning id into new_id;
  select count(*) into n from live_sessions where started_at >= today_start;
  return jsonb_build_object('status', 'ok', 'id', new_id, 'n', n);
end $$;

-- cancel: the token could not be made, so the reader's conversation is not used up
create or replace function public.live_talk_cancel(p_id bigint) returns void
language sql security definer set search_path = public as $$
  delete from live_sessions where id = p_id
$$;

revoke all on function public.live_talk_begin(uuid, integer, text, integer, integer, integer) from public, anon, authenticated;
revoke all on function public.live_talk_cancel(bigint) from public, anon, authenticated;
grant execute on function public.live_talk_begin(uuid, integer, text, integer, integer, integer) to service_role;
grant execute on function public.live_talk_cancel(bigint) to service_role;
