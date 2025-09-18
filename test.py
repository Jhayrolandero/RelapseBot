import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os
from collections import deque
from dotenv import load_dotenv
import random
import time

load_dotenv()

# Hardcoded for now
RELAPSE_SONGS = [
    "Hanggang Kailan - Umuwi Ka Na Baby",
    "Moonstar 88 - Migraine",
    "Sana",
    "Janice",
    "With A Smile"
]

USER_APPRECIATION_MESSAGES = [
    "{user.mention}, your music taste is 🔥!",
    "Thanks for the vibes, {user.mention}! 🎵",
    "{user.mention} really knows how to set the mood! 💫",
    "Great pick, {user.mention}! This is my jam! 🎶",
    "{user.mention}, you're the MVP of this playlist! 🏆"
]


DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Music queues for each guild
music_queues = {}
voice_clients = {}
current_song_info = {}
# Add to global variables
random_message_tasks = {}

# yt-dlp options
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        
        if 'entries' in data:
            # Take first item from a playlist
            data = data['entries'][0]
        
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

    @classmethod
    async def search_youtube(cls, search_query, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{search_query}", download=False))
            if 'entries' in data and len(data['entries']) > 0:
                return data['entries'][0]['webpage_url']
        except Exception as e:
            print(f"Search error: {e}")
        return None


def inVoiceChecker():
    pass


async def send_random_hugot_line(ctx, guild_id):
    """Send random messages while music is playing"""
    while True:
        voice_client = voice_clients.get(guild_id)
        
        # Stop if no music is playing
        if not voice_client or not voice_client.is_playing():
            break
            
        # Wait random time between 30-120 seconds
        wait_time = random.randint(5, 10)
        await asyncio.sleep(wait_time)
        
        # Check again if still playing
        if voice_client and voice_client.is_playing():
            random_message = random.choice(USER_APPRECIATION_MESSAGES).format(user=ctx.author)
            await ctx.send(random_message)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

@bot.command(name='join', help='Joins a voice channel')
async def join(ctx):
    if not ctx.message.author.voice:
        await ctx.send("You are not connected to a voice channel!")
        return
    
    channel = ctx.message.author.voice.channel
    voice_client = await channel.connect()
    voice_clients[ctx.guild.id] = voice_client
    await ctx.send(f"Joined {channel}")

@bot.command(name='leave', help='Leaves the voice channel')
async def leave(ctx):
    voice_client = voice_clients.get(ctx.guild.id)
    if voice_client:
        await voice_client.disconnect()
        del voice_clients[ctx.guild.id]
        if ctx.guild.id in music_queues:
            del music_queues[ctx.guild.id]
        await ctx.send("Disconnected from voice channel!")
    else:
        await ctx.send("Bot is not connected to a voice channel!")

@bot.command(name='relapse', help='Plays a random relapse song')
async def relapse(ctx):
    if ctx.guild.id not in voice_clients:
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            voice_client = await channel.connect()
            voice_clients[ctx.guild.id] = voice_client
        else:
            await ctx.send("You need to be in a voice channel!")
            return

    # Play a random relapse song
    song = random.choice(RELAPSE_SONGS)
    
    if ctx.guild.id not in music_queues:
            music_queues[ctx.guild.id] = deque()
    
    try:
        url = await YTDLSource.search_youtube(song)
        # Check if it's a URL or search query
       
        if not url:
            await ctx.send("Could not find any results for your search!")
            return
        
        # Get video info
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        
        if 'entries' in data:
            data = data['entries'][0]
        
        song_info = {
            'url': url,
            'title': data['title'],
            'duration': data.get('duration', 0),
            'requester': ctx.author.name
        }
        
        # Add to queue
        music_queues[ctx.guild.id].append(song_info)
        
        if not voice_client.is_playing():
            await play_next(ctx)
        else:
            await ctx.send(f"Added to queue: **{song_info['title']}**")
            
    except Exception as e:
        await ctx.send(f"An error occurred: {str(e)}")
    
    await ctx.send(f"Now playing: {song}")

@bot.command(name='play', help='Plays audio from YouTube')
async def play(ctx, *, search):
    # Join voice channel if not already connected
    if ctx.guild.id not in voice_clients:
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            voice_client = await channel.connect()
            voice_clients[ctx.guild.id] = voice_client
        else:
            await ctx.send("You need to be in a voice channel!")
            return
    
    voice_client = voice_clients[ctx.guild.id]
    
    # Initialize queue if it doesn't exist
    if ctx.guild.id not in music_queues:
        music_queues[ctx.guild.id] = deque()
    
    try:
        # Check if it's a URL or search query
        if not (search.startswith('http://') or search.startswith('https://')):
            # Search YouTube
            url = await YTDLSource.search_youtube(search)
            if not url:
                await ctx.send("Could not find any results for your search!")
                return
        else:
            url = search
        
        # Get video info
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        
        if 'entries' in data:
            data = data['entries'][0]
        
        song_info = {
            'url': url,
            'title': data['title'],
            'duration': data.get('duration', 0),
            'requester': ctx.author.name
        }
        
        # Add to queue
        music_queues[ctx.guild.id].append(song_info)
        
        if not voice_client.is_playing():
            await play_next(ctx)
        else:
            await ctx.send(f"Added to queue: **{song_info['title']}**")
            
    except Exception as e:
        await ctx.send(f"An error occurred: {str(e)}")

async def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        # Stop random messages when queue is empty
        if guild_id in random_message_tasks:
            random_message_tasks[guild_id].cancel()
            del random_message_tasks[guild_id]
        
        return
    
    voice_client = voice_clients.get(guild_id)
    if not voice_client:
        return
    
    song_info = music_queues[guild_id].popleft()
    
    try:
        player = await YTDLSource.from_url(song_info['url'], loop=bot.loop, stream=True)
        voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop) if not e else print(f"Player error: {e}"))
        
        # Start random message task if not already running
        if guild_id not in random_message_tasks:
            task = asyncio.create_task(send_random_hugot_line(ctx, guild_id))
            random_message_tasks[guild_id] = task
        
        duration_str = f"{song_info['duration']//60}:{song_info['duration']%60:02d}" if song_info['duration'] else "Unknown"
        embed = discord.Embed(
            title="Now Playing",
            description=f"**{song_info['title']}**\nDuration: {duration_str}\nRequested by: {song_info['requester']}",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
        
        # Store current song info
        current_song_info[guild_id] = {
            'title': song_info['title'],
            'duration': song_info['duration'],
            'requester': song_info['requester'],
            'start_time': time.time()
        }
        
    except Exception as e:
        await ctx.send(f"Error playing song: {str(e)}")
        # Try to play next song if there's an error
        if len(music_queues[guild_id]) > 0:
            await play_next(ctx)

@bot.command(name='pause', help='Pauses the current song')
async def pause(ctx):
    voice_client = voice_clients.get(ctx.guild.id)
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await ctx.send("Music paused ⏸️")
    else:
        await ctx.send("No music is currently playing!")

@bot.command(name='resume', help='Resumes the current song')
async def resume(ctx):
    voice_client = voice_clients.get(ctx.guild.id)
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await ctx.send("Music resumed ▶️")
    else:
        await ctx.send("Music is not paused!")

@bot.command(name='stop', help='Stops the current song and clears the queue')
async def stop(ctx):
    voice_client = voice_clients.get(ctx.guild.id)
    if voice_client:
        if ctx.guild.id in music_queues:
            music_queues[ctx.guild.id].clear()
            
             # Cancel random message task
        if ctx.guild.id in random_message_tasks:
            random_message_tasks[ctx.guild.id].cancel()
            del random_message_tasks[ctx.guild.id]
            
        voice_client.stop()
        await ctx.send("Music stopped and queue cleared! 🛑")
    else:
        await ctx.send("Bot is not connected to a voice channel!")

@bot.command(name='skip', help='Skips the current song')
async def skip(ctx):
    voice_client = voice_clients.get(ctx.guild.id)
    if voice_client and voice_client.is_playing():
        voice_client.stop()  # This will trigger play_next
        await ctx.send("Song skipped! ⏭️")
    else:
        await ctx.send("No music is currently playing!")

@bot.command(name='queue', help='Shows the current music queue')
async def show_queue(ctx):
    guild_id = ctx.guild.id
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        await ctx.send("The queue is empty!")
        return
    
    queue_list = list(music_queues[guild_id])
    embed = discord.Embed(title="Music Queue", color=0x0099ff)
    
    for i, song in enumerate(queue_list[:10]):  # Show first 10 songs
        duration_str = f"{song['duration']//60}:{song['duration']%60:02d}" if song['duration'] else "Unknown"
        embed.add_field(
            name=f"{i+1}. {song['title']}",
            value=f"Duration: {duration_str} | Requested by: {song['requester']}",
            inline=False
        )
    
    if len(queue_list) > 10:
        embed.add_field(name="...", value=f"And {len(queue_list) - 10} more songs", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='clear', help='Clears the music queue')
async def clear_queue(ctx):
    if ctx.guild.id in music_queues:
        music_queues[ctx.guild.id].clear()
        await ctx.send("Queue cleared! 🗑️")
    else:
        await ctx.send("Queue is already empty!")

@bot.command(name='nowplaying', aliases=['np'], help='Shows the currently playing song')
async def now_playing(ctx):
    guild_id = ctx.guild.id
    voice_client = voice_clients.get(guild_id)
    
    if not voice_client or not voice_client.is_playing():
        await ctx.send("No music is currently playing!")
        return
    
    if guild_id not in current_song_info:
        await ctx.send("No song information available!")
        return
    
    song = current_song_info[guild_id]
    elapsed_time = time.time() - song['start_time']
    total_duration = song['duration']
    remaining_time = max(0, total_duration - elapsed_time)
    
    # Create progress bar
    progress_percentage = min(elapsed_time / total_duration, 1.0) if total_duration > 0 else 0
    bar_length = 20
    filled_length = int(bar_length * progress_percentage)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    elapsed_str = f"{int(elapsed_time//60)}:{int(elapsed_time%60):02d}"
    total_str = f"{int(total_duration//60)}:{int(total_duration%60):02d}" if total_duration else "Unknown"
    remaining_str = f"{int(remaining_time//60)}:{int(remaining_time%60):02d}"
    
    embed = discord.Embed(
        title="Now Playing",
        description=f"**{song['title']}**\n{bar}\n{elapsed_str} / {total_str}\nTime remaining: {remaining_str}\nRequested by: {song['requester']}",
        color=0x00ff00
    )
    await ctx.send(embed=embed)


# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Missing required argument! Check `!help` for command usage.")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("Command not found! Use `!help` to see available commands.")
    else:
        await ctx.send(f"An error occurred: {str(error)}")

# Replace 'YOUR_BOT_TOKEN' with your actual bot token
bot.run(DISCORD_BOT_TOKEN)