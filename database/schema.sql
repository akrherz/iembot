
CREATE TABLE iembot_webhooks(
  channel varchar,
  url varchar);

CREATE TABLE iembot_room_syndications (
	roomname character varying(64),    
	endpoint character varying(64),    
	convtype character(1));


CREATE TABLE iembot_fb_access_tokens (
    fbpid bigint,
    access_token text
);
CREATE TABLE iembot_fb_subscriptions (
    fbpid bigint,
    channel character varying
);

---
--- Table to track iembot's use of social media
---
CREATE TABLE iembot_social_log(
  valid timestamp with time zone default now(),
  medium varchar(24),
  source varchar(256),
  resource_uri varchar(256),
  message text,
  message_link varchar(256),
  response text,
  response_code int
);
CREATE index iembot_social_log_valid_idx on iembot_social_log(valid);

---
--- IEMBOT Twitter Page subscriptions
---
CREATE TABLE iembot_twitter_oauth(
  user_id bigint NOT NULL UNIQUE,
  screen_name text,
  access_token text,
  access_token_secret text,
  created timestamptz DEFAULT now(),
  updated timestamptz DEFAULT now()
);

CREATE TABLE iembot_twitter_subs(
  user_id bigint REFERENCES iembot_twitter_oauth(user_id),
  screen_name varchar(128),
  channel varchar(64)
);
CREATE UNIQUE index iembot_twitter_subs_idx on
 iembot_twitter_subs(screen_name, channel);


CREATE TABLE iembot_channels(
  id varchar not null UNIQUE,
  name varchar,
  channel_key character varying DEFAULT substr(md5((random())::text), 0, 12)
);


---
--- IEMBot rooms
---
CREATE TABLE iembot_room_subscriptions (
    roomname character varying(64),
    channel character varying(24)
);
CREATE UNIQUE index iembot_room_subscriptions_idx on
  iembot_room_subscriptions(roomname, channel);

---
--- IEMBot room subscriptions
---
CREATE TABLE iembot_rooms (
    roomname varchar(64),
    fbpage varchar,
    twitter varchar
);


