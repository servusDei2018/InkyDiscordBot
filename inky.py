import json
import os
import requests
import MySQLdb
import discord
from discord.ext import tasks, commands
import time

#Instanciate Discord Bot
client = discord.Client()
client = commands.Bot(command_prefix='$')


#Variable Assignment
loop = 0
host = 'REDACTED'
user = 'REDACTED'
passwd = 'REDACTED'
db = 'REDACTED'
nonClannieIDs = []
headers = {'X-API-KEY': 'REDACTED'}

#Updates SQL database of all clanmembers. Technically this is inefficent, because it runs every time on mainloop as a part of the clannieUpdate function. But meh
def clannieInsert(inputDestinyDisplayName, inputDestinyMembershipID, inputBungieDisplayName, inputBungieMembershipID):
	conn = MySQLdb.connect(host, user, passwd, db)
	cursor = conn.cursor()

	# Finer point of the SQL syntax here, REPLACE vs INSERT. Since this gets run more than once, if a simple insert was used, exceptions would be raised since entries already exist with the PK
	#  So by using replace, we overwrite the data, avoiding the exception. This has the aide effect of keeping the database up to date on username changes. 
	#  One major shortcoming of the code that needs to be addressed, is that is someone leaves the clan, the database does not remove them from the clan roster.
	cursor.execute('REPLACE INTO clannies (destinyDisplayName, destinyMembershipID, bungieDisplayName, bungieMembershipID) VALUES (%s, %s, %s, %s);', [inputDestinyDisplayName, inputDestinyMembershipID, inputBungieDisplayName, inputBungieMembershipID])
	result = cursor.fetchall()

	conn.commit()
	conn.close()

#Fetch Clan roster from API
def clannieUpdate():
	headers = {'X-API-KEY': 'REDACTED'}
	r = requests.get('https://www.bungie.net/Platform/GroupV2/1890137/Members/', headers=headers)
	rawClanniesJSON = r.json()
	clanniesJSON = rawClanniesJSON["Response"]["results"]

	global onlineClannies, clannieIDs
	onlineClannies = []
	clannieIDs = []

	for clannie in clanniesJSON:
		destinyMembershipID = clannie["destinyUserInfo"]["membershipId"]
		destinyDisplayName = clannie["destinyUserInfo"]["LastSeenDisplayName"].encode("utf-8")
		bungieMembershipID = clannie["bungieNetUserInfo"]["membershipId"]
		bungieDisplayName = clannie["bungieNetUserInfo"]["displayName"].encode("utf-8")
		clannieInsert(destinyDisplayName, destinyMembershipID, bungieDisplayName, bungieMembershipID)
		clannieIDs.append(destinyMembershipID)
		#If member is online, add them to list of fireteams to check. Note online status is not effected by steam online status.
		if clannie["isOnline"] == True:
			onlineClannies.append(clannie["destinyUserInfo"]["membershipId"])
			print(f"{destinyDisplayName} is online")

#Fetch Weapon Statistics from API.
def apiRequestStats(val1, val2):
	global headers
	print("making api call")
	r = requests.get(f'https://www.bungie.net/Platform/Destiny2/1/Account/{val1}/Stats/?groups={val2}', headers=headers)
	rawStatsJSON = r.json()
	if rawStatsJSON["ErrorCode"] != 1:
		r = requests.get(f'https://www.bungie.net/Platform/Destiny2/3/Account/{val1}/Stats/?groups={val2}', headers=headers)
		rawStatsJSON = r.json()
		if rawStatsJSON["ErrorCode"] !=1:
			rawStatsJSON = 0
	
	return rawStatsJSON

#Fetch Fireteam members of given player.
def apiRequestFireteam(val1):
	global headers
	r = requests.get(f'https://www.bungie.net/Platform/Destiny2/1/Profile/{val1}/?components=1000', headers=headers)
	rawStatsJSON = r.json()
	if rawStatsJSON["ErrorCode"] != 1:
		r = requests.get(f'https://www.bungie.net/Platform/Destiny2/3/Profile/{val1}/?components=1000', headers=headers)
		rawStatsJSON = r.json()
		if rawStatsJSON["ErrorCode"] !=1:
			rawStatsJSON = 0
	
	return rawStatsJSON

#Matches ID to display name from DB.
def getClannieDisplayNameFromID(mid):
	conn = MySQLdb.connect(host, user, passwd, db)
	cursor = conn.cursor()
	cursor.execute('SELECT destinyDisplayName FROM clannies WHERE destinyMembershipID=%s', [mid])
	result = cursor.fetchall()
	conn.commit()
	conn.close()
	return result

#Backend handler function to persist blacklist additions by adding them to DB. REPLACE is used here because I'm too lazy to have it check if an ID is blacklisted already.
def addToBlacklist(mid):
	epoch = int(time.time())
	conn = MySQLdb.connect(host, user, passwd, db)
	cursor = conn.cursor()
	cursor.execute('REPLACE INTO blacklist (membershipID, epoch) VALUES (%s, %s)', [mid, epoch])
	result = cursor.fetchall()
	conn.commit()
	conn.close()
	return result

#Main loop, exectution handled by the discord bot via means of asyncio. 
@tasks.loop(minutes=2)
async def mainloop():

	#Sets bot status to indicate it is updating and will not respond to commands.
	activity = discord.Activity(name='Clan Fireteams [X]', type=discord.ActivityType.watching)
	await client.change_presence(activity=activity)

	#Perform update of roster and online users.
	clannieUpdate()

	#Make sure the bot is connected to discord.
	await client.wait_until_ready()

	global clannieIDs, nonClannieIDs, blacklist, loop
	clannienum = 0
	
	# Resets "processed" list of non clannies. Otherwise, people would only show up once and never again until the script restarts, needs fine tuning.
	if loop % 20 == 0:
		nonClannieIDs = []

	#Refresh Discord connection for no reason
	if loop % 100 == 0:
		await client.close()
		await client.connect(reconnect=True)

	loop = loop + 1

	#Fetch Blacklist
	conn = MySQLdb.connect(host, user, passwd, db)
	cursor = conn.cursor()
	cursor.execute('SELECT membershipID FROM blacklist')
	MIDresult = cursor.fetchall()
	blacklist = [MIDresult]
	conn.close()


	#For each clan member whom is online, fetch fireteam members, if none, skip.
	for clannie in onlineClannies:
		clannienum = clannienum + 1
		headers = {'X-API-KEY': 'REDACTED'}
		rawTransitoryJSON = apiRequestFireteam(clannie)
		if rawTransitoryJSON == 0:
			continue
		try: 
			fireteamMembers = rawTransitoryJSON["Response"]["profileTransitoryData"]["data"]["partyMembers"]
		except:
			break
		
		for member in fireteamMembers:

			#For blacklist ID, check if matched fireteam member id and notify if needed.
			for mid in blacklist[0]:
				if member["membershipId"] == mid[0]:
					print("inblacklist")
					result = getClannieDisplayNameFromID(clannie)
					embed = discord.Embed(title=member["displayName"], description=member["membershipId"], color=0xffffff)
					embed.add_field(name="Playing With:", value=result[0][0], inline=False)
					channel = client.get_channel(614647064281743373)
					await channel.send(embed=embed)

			#For fireteam member, ensure member is not in the clan, and has not been processes in the past 20 loops. Otherwise, check their stats.
			if member["membershipId"] not in clannieIDs:
				if member["membershipId"] not in nonClannieIDs:
					nonClannieIDs.append(member["membershipId"])
					print(f"Non Clan Member in Fireteam: {member['displayName']}")

					nonClannieStats = apiRequestStats(member["membershipId"], "Weapons")
					if nonClannieStats == 0:
						break

					baseAllPVP = nonClannieStats["Response"]["mergedAllCharacters"]["results"]["allPvP"]["allTime"]
					autoPrecPer = baseAllPVP["weaponKillsPrecisionKillsAutoRifle"]["basic"]["displayValue"]
					bowPrecPer = baseAllPVP["weaponKillsPrecisionKillsBow"]["basic"]["displayValue"]
					hcPrecPer = baseAllPVP["weaponKillsPrecisionKillsHandCannon"]["basic"]["displayValue"]
					tracePrecPer = baseAllPVP["weaponKillsPrecisionKillsTraceRifle"]["basic"]["displayValue"]
					mgPrecPer = baseAllPVP["weaponKillsPrecisionKillsMachineGun"]["basic"]["displayValue"]
					pulsePrecPer = baseAllPVP["weaponKillsPrecisionKillsPulseRifle"]["basic"]["displayValue"]
					scoutPrecPer = baseAllPVP["weaponKillsPrecisionKillsScoutRifle"]["basic"]["displayValue"]
					sniperPrecPer = baseAllPVP["weaponKillsPrecisionKillsSniper"]["basic"]["displayValue"]
					smgPrecPer = baseAllPVP["weaponKillsPrecisionKillsSubmachinegun"]["basic"]["displayValue"]

					nonClannieStatsList = [autoPrecPer, bowPrecPer, hcPrecPer, tracePrecPer, mgPrecPer, pulsePrecPer, scoutPrecPer, sniperPrecPer, smgPrecPer]
				
					#If any stat is above 85% notify sus.
					for stat in nonClannieStatsList:
						if stat >= "85%":
							result = getClannieDisplayNameFromID(clannie)
							
							embed = discord.Embed(title=member["displayName"], description=member["membershipId"], color=0xffff00)
							embed.add_field(name="Playing With:", value=result[0][0], inline=False)
							
							embed.add_field(name="Sniper %", value=sniperPrecPer, inline=True)
							embed.add_field(name="Hand Cannon %", value=hcPrecPer, inline=True)
							embed.add_field(name="Auto %", value=autoPrecPer, inline=True)

							embed.add_field(name="Pulse %", value=pulsePrecPer, inline=True)
							embed.add_field(name="Scout %", value=scoutPrecPer, inline=True)
							embed.add_field(name="SMG %", value=smgPrecPer, inline=True)

							embed.add_field(name="Bow %", value=bowPrecPer, inline=True)
							embed.add_field(name="MG %", value=mgPrecPer, inline=True)
							embed.add_field(name="Trace %", value=tracePrecPer, inline=True)
							channel = client.get_channel(614647064281743373)
							await channel.send(embed=embed)
							break
	#Log loop, and clear "working" status.
	print(f"loop #{loop} done.")
	activity = discord.Activity(name='Clan Fireteams [0]', type=discord.ActivityType.watching)
	await client.change_presence(activity=activity)

#Bot event handlers

#Start mainloop once connection is established.
@client.event
async def on_ready():
    print('We have logged in as {0.user}'.format(client))
    mainloop.start()

#Resgister blacklist command and pass arg to function
@client.command()
async def blacklist(ctx, arg):
    channel = client.get_channel(614647064281743373)
    addToBlacklist(arg)
    await channel.send(arg)

#start
client.run('REDACTED', reconnect=True)

