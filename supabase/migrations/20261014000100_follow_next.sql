-- One-time "next article" alert (owner, Oct 14 2026): the home page's Refresh button, when no new article is there yet,
-- asks to be told about the next one. It is a follow of kind 'next' (key 'any') that notify.py spends (deletes) when it
-- sends that one notification.
alter table public.follows drop constraint if exists follows_kind_check;
alter table public.follows add constraint follows_kind_check
  check (kind in ('section', 'place', 'entity', 'story', 'recap', 'next'));
