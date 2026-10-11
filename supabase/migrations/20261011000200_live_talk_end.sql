-- "Talk to the article": a conversation that has ended frees its place at once (owner, Oct 11 2026: three people were
-- turned away). Until now a row counted as "running" for the whole 8 minutes after it started, whether the reader had
-- hung up after 10 seconds or the connection had failed. The browser now tells the function when it ends (live_talk_end);
-- a row with ended_at no longer counts toward the site-wide limit, and neither does one whose browser has stopped saying it is there (45 s). The reader's day (p_daily) still counts every start.

alter table public.live_sessions add column if not exists ended_at timestamptz;
-- the browser says "still here" every 15 s (live_talk_ping); a conversation silent for 45 s is over (a closed tab, a dead phone)
alter table public.live_sessions add column if not exists last_seen timestamptz not null default now();

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
  perform pg_advisory_xact_lock(7001);
  if (select count(*) from live_sessions where reader = p_reader and started_at >= today_start) >= p_daily then
    return jsonb_build_object('status', 'limit');
  end if;
  if (select count(*) from live_sessions where ended_at is null and started_at > now() - make_interval(secs => p_seconds) and last_seen > now() - interval '45 seconds') >= p_concurrent then
    return jsonb_build_object('status', 'busy');
  end if;
  delete from live_sessions where started_at < now() - interval '14 days';
  insert into live_sessions (reader, story_id, lang) values (p_reader, p_story, p_lang) returning id into new_id;
  select count(*) into n from live_sessions where started_at >= today_start;
  return jsonb_build_object('status', 'ok', 'id', new_id, 'n', n);
end $$;

-- end: the conversation is over (only its own reader can end it; ending twice does nothing)
create or replace function public.live_talk_end(p_id bigint, p_reader uuid) returns void
language sql security definer set search_path = public as $$
  update live_sessions set ended_at = now() where id = p_id and reader = p_reader and ended_at is null
$$;

revoke all on function public.live_talk_end(bigint, uuid) from public, anon, authenticated;
grant execute on function public.live_talk_end(bigint, uuid) to service_role;

-- ping: the conversation is still going (only its own reader)
create or replace function public.live_talk_ping(p_id bigint, p_reader uuid) returns void
language sql security definer set search_path = public as $$
  update live_sessions set last_seen = now() where id = p_id and reader = p_reader and ended_at is null
$$;

revoke all on function public.live_talk_ping(bigint, uuid) from public, anon, authenticated;
grant execute on function public.live_talk_ping(bigint, uuid) to service_role;
