-- Migration: Director/Admin user management functions
-- Run in: supabase.com → your project → SQL Editor

-- Update any user's profile (Directors and Admins only)
create or replace function update_user_profile(
  target_id  uuid,
  new_name   text,
  new_username text
) returns void language plpgsql security definer as $$
declare
  caller_role text;
begin
  select role into caller_role from profiles where id = auth.uid();
  if caller_role not in ('Director', 'Admin') then
    raise exception 'Only Directors and Admins can edit other users profiles.';
  end if;

  -- Ensure username is not already taken by someone else
  if exists (
    select 1 from profiles
    where lower(username) = lower(new_username)
    and id <> target_id
  ) then
    raise exception 'Username "%" is already taken.', new_username;
  end if;

  update profiles
  set full_name = new_name,
      username  = new_username
  where id = target_id;
end;
$$;

-- Delete a user account entirely (Directors and Admins only)
create or replace function delete_user_account(target_user_id uuid)
returns void language plpgsql security definer as $$
declare
  caller_role text;
begin
  select role into caller_role from profiles where id = auth.uid();
  if caller_role not in ('Director', 'Admin') then
    raise exception 'Only Directors and Admins can delete users.';
  end if;

  if target_user_id = auth.uid() then
    raise exception 'You cannot delete your own account.';
  end if;

  -- Remove profile first (FK constraint)
  delete from profiles where id = target_user_id;

  -- Remove their orders attribution (keep orders but clear user link)
  update orders set user_id = auth.uid() where user_id = target_user_id;

  -- Delete the auth user
  delete from auth.users where id = target_user_id;
end;
$$;
