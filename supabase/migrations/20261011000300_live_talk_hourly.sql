-- "Talk to the article": the reader's limit is per HOUR now (owner, Oct 11 2026: "per hour limits rather than per day").
-- A rolling hour: a reader may start p_hourly conversations in any 60 minutes, so someone studying can keep going and
-- nobody waits until midnight. p_daily stays as a high backstop per IST day (a bug or a script cannot burn the site's
-- Gemini quota). The site-wide limit at the same moment (p_concurrent) is what protects the Live model's tokens a minute.
-- Replaces the version in 20261011000200 (a new argument, so the old one is dropped first).

drop function if exists public.live_talk_begin(uuid, integer, text, integer, integer, integer);

create or replace function public.live_talk_begin(
  p_reader uuid, p_story integer, p_lang text, p_hourly integer, p_daily integer, p_concurrent integer, p_seconds integer
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  today_start timestamptz := (date_trunc('day', now() at time zone 'Asia/Kolkata')) at time zone 'Asia/Kolkata';
  new_id bigint;
  n integer;
  oldest timestamptz;
begin
  if p_reader is null then return jsonb_build_object('status', 'login'); end if;
  if p_lang not in ('en', 'hi') or p_hourly < 1 or p_daily < 1 or p_concurrent < 1 or p_seconds < 30 then
    return jsonb_build_object('status', 'bad');
  end if;
  if not exists (select 1 from published where story_id = p_story) then
    return jsonb_build_object('status', 'gone');
  end if;
  perform pg_advisory_xact_lock(7001);
  -- this hour: when the oldest of the reader's last p_hourly conversations falls out of the hour, a place is free again
  if (select count(*) from live_sessions where reader = p_reader and started_at > now() - interval '1 hour') >= p_hourly then
    select min(started_at) into oldest from (
      select started_at from live_sessions where reader = p_reader and started_at > now() - interval '1 hour'
      order by started_at desc limit p_hourly) last_ones;
    return jsonb_build_object('status', 'limit', 'retry_minutes', greatest(1, ceil(extract(epoch from (oldest + interval '1 hour' - now())) / 60)::int));
  end if;
  if (select count(*) from live_sessions where reader = p_reader and started_at >= today_start) >= p_daily then
    return jsonb_build_object('status', 'limit', 'retry_minutes', 60);
  end if;
  if (select count(*) from live_sessions where ended_at is null and started_at > now() - make_interval(secs => p_seconds) and last_seen > now() - interval '45 seconds') >= p_concurrent then
    return jsonb_build_object('status', 'busy');
  end if;
  delete from live_sessions where started_at < now() - interval '14 days';
  insert into live_sessions (reader, story_id, lang) values (p_reader, p_story, p_lang) returning id into new_id;
  select count(*) into n from live_sessions where started_at >= today_start;
  return jsonb_build_object('status', 'ok', 'id', new_id, 'n', n);
end $$;

revoke all on function public.live_talk_begin(uuid, integer, text, integer, integer, integer, integer) from public, anon, authenticated;
grant execute on function public.live_talk_begin(uuid, integer, text, integer, integer, integer, integer) to service_role;
