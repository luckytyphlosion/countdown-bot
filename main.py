import discord
from discord.ext import commands
import discord.utils
import yaml
import asyncio
import math
import contextvars
import sys
import datetime
import re

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

config = None

atc_timer_tasks = {}

def is_finite(x):
    return not math.isnan(x) and not math.isinf(x)

def load_config():
    global config

    with open("config.yml", "r") as f:
        config = yaml.safe_load(f)

class DiscordObjs:
    __slots_ = ("guild", "atc_role")

    def __init__(self):
        self.guild = None
        self.atc_role = None

discord_objs = DiscordObjs()

def load_discord_objs(bot_local):
    global config

    discord_objs.guild = bot_local.get_guild(config["guild_id"])
    discord_objs.atc_role = discord.utils.get(discord_objs.guild.roles, id=config["atc_role_id"])

def pretty_local_time():
    return datetime.datetime.now().strftime('%Y-%m-%d %I:%M %p')

GENERIC_HELP_MESSAGE = """Here are some examples of how to use the command:
- `!c`: Announces you are available for 1 hour.
- `!c 2h` OR `!c 2` OR `!c 2:00`: Announces you are available for 2 hours.
- `!c 1h45m` OR `!c 1.75` OR `!c 1:45`: Announces you are available for 1 hour and 45 minutes.
- `!c 15m` OR `!c 0.25` OR `!c 0:15`: Announces you are available for 15 minutes."""

duration_regex = re.compile(r"^(?:([0-9]+)h)?(?:([0-9]+)m)?$")
duration_2_regex = re.compile(r"^([0-9]+):([0-9]{2})?$")

def parse_hours_only(param):
    hours = None

    try:
        hours = float(param)
        if not is_finite(hours):
            hours = None
    except ValueError:
        pass

    return hours

def parse_complex_duration(param):
    duration = None
    #error_message = None

    match_obj = duration_regex.match(param)
    if not match_obj:
        match_obj = duration_2_regex.match(param)

    if match_obj:
        hours = match_obj.group(1)
        minutes = match_obj.group(2)
        if hours is not None or minutes is not None:
            if hours is None:
                hours = 0
            if minutes is None:
                minutes = 0

            try:
                duration = int(hours) * 3600 + int(minutes) * 60
            except ValueError:
                pass

    return duration

def parse_duration(param):
    error_message = None
    duration = None

    if len(param) > 10:
        error_message = f"To prevent memory errors, the provided duration can be at most 10 characters long. {GENERIC_HELP_MESSAGE}"
    else:
        if param == "":
            duration = 3600
        else:
            hours = parse_hours_only(param)
            if hours is not None:
                duration = int((((hours * 3600) + 30) // 60) * 60)
            else:
                duration = parse_complex_duration(param)

        if duration is None:
            error_message = f"Please provide how long you are Available to Countdown for. {GENERIC_HELP_MESSAGE}"
        elif duration == 0:
            error_message = f"You cannot say that you are Available to Countdown for 0 hours. {GENERIC_HELP_MESSAGE}"
        elif duration < 0:
            error_message = f"You cannot say that you are Available to Countdown for less than 0 hours. {GENERIC_HELP_MESSAGE}"
        elif duration > 86400:
            error_message = f"You cannot say that you are Available to Countdown for more than 24 hours (so people don't forget to become unavailable). {GENERIC_HELP_MESSAGE}"

    return duration, error_message

def generate_duration_str(duration_as_minutes):
    #print(f"duration_as_minutes: {duration_as_minutes}")
    minutes = duration_as_minutes % 60
    hours = duration_as_minutes // 60

    duration_str_parts = []

    if hours != 0:
        if hours == 1:
            hours_str = f"{hours} hour"
        else:
            hours_str = f"{hours} hours"

        duration_str_parts.append(hours_str)

    if minutes != 0:
        if minutes == 1:
            minutes_str = f"{minutes} minute"
        else:
            minutes_str = f"{minutes} minutes"

        duration_str_parts.append(minutes_str)

    duration_str = f"{' and '.join(duration_str_parts)} ({hours}:{minutes:02d})"

    return duration_str

async def handle_available_timer(duration_as_minutes, user_id):
    #print(f"Duration as minutes: {duration_as_minutes}")
    duration = duration_as_minutes * 60
    await asyncio.sleep(duration)
    #print("After sleep")
    member = discord_objs.guild.get_member(user_id)
    print(f"Removing {member.name} from atc timer")
    await member.remove_roles(discord_objs.atc_role)

def add_atc_timer_task(user_id, duration_as_minutes):
    atc_timer_tasks[user_id] = asyncio.create_task(handle_available_timer(duration_as_minutes, user_id))

def cancel_atc_timer_task(user_id):
    atc_timer_task = atc_timer_tasks.get(user_id)
    # overwrite if existing
    if atc_timer_task is not None and not atc_timer_task.done():
        atc_timer_task.cancel()
        atc_timer_tasks[user_id] = None

async def add_atc_role_and_setup_timer_for_user(member, duration_as_minutes):
    cancel_atc_timer_task(member.id)
    await member.add_roles(discord_objs.atc_role)
    add_atc_timer_task(member.id, duration_as_minutes)

async def print_and_send(ctx, message):
    print(f"[{pretty_local_time()}] {message}")
    await ctx.send(message)

@bot.command()
async def c(ctx):
    response_contents = ""
    param = ctx.message.content.strip().split(maxsplit=1)
    if len(param) == 1:
        param = ""
    else:
        param = param[1]

    duration, error_message = parse_duration(param)
    if error_message is not None:
        await print_and_send(ctx, f"Error: {error_message}")
    else:
        duration_as_minutes = max(duration//60, 1)
        duration_str = generate_duration_str(duration_as_minutes)

        member = ctx.message.author

        await add_atc_role_and_setup_timer_for_user(member, duration_as_minutes)
        response_contents = f"You are now available to Countdown for {duration_str}, {ctx.message.author.name}"
        await print_and_send(ctx, response_contents)

@bot.command()
async def d(ctx):
    member = ctx.message.author
    cancel_atc_timer_task(member.id)
    await member.remove_roles(discord_objs.atc_role)
    response_contents = f"You are no longer available to Countdown, {member.name}"
    await print_and_send(ctx, response_contents)

@bot.event
async def on_ready():
    print("Running!")
    load_discord_objs(bot)
    
def main():
    load_config()

    token = config["token"]
    bot.run(token)

if __name__ == "__main__":
    main()
