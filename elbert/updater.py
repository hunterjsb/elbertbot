# from elbert.asyncriothandle import AsyncRequester
from asyncriothandle import AsyncRequester
import json
import datetime
import time
import requests

# File-paths for the data
LEAGUE_FP = "../json/silverfantasy.json"
GAMES_FP = "../json/soloqgames.json"
REQ_PER_SEC = 20


def last_friday():  # get last friday as a timestamp (in ms maybe)
    today = datetime.datetime.today()
    friday = today + datetime.timedelta((4 - today.weekday()) % 7) - datetime.timedelta(6)
    return round(friday.timestamp() * 1000)


def get_champ(champ_id):
    champ_dat = requests.get('http://ddragon.leagueoflegends.com/cdn/10.10.3208608/data/en_US/champion.json').json()[
        'data']
    for champ in champ_dat:
        cid = int(champ_dat[champ]['key'])
        if cid == champ_id:
            return champ


lin_mmr_dict = {'IRON IV': 0, 'IRON III': 250, 'IRON II': 500, 'IRON I': 750, 'BRONZE IV': 1000, 'BRONZE III':
                1250, 'BRONZE II': 1500, 'BRONZE I': 1750, 'SILVER IV': 2000, 'SILVER III': 2250, 'SILVER II':
                2500, 'SILVER I': 2750, 'GOLD IV': 3000, 'GOLD III': 3250, 'GOLD II': 3500, 'GOLD I': 3750,
                'PLATINUM IV': 4000, 'PLATINUM III': 4250, 'PLATINUM II': 4500, 'PLATINUM I': 4750,
                'DIAMOND IV': 5000, 'DIAMOND III': 5500, 'DIAMOND II': 6000, 'DIAMOND I': 6500, 'MASTER I':
                7000, 'GRANDMASTER I': 7500, 'CHALLENGER I': 8000}


class Updater:
    chunks_sent = 0

    """class that takes arguments and decides what it needs to retrieve in order to update the relevant JSON files"""
    def __init__(self, request_type: str):
        """open the two json files, takes the request type as input"""
        with open(LEAGUE_FP) as f:
            self.league = json.load(f)
        with open(GAMES_FP) as f2:
            self.games = json.load(f2)

        self.erred = {}
        self.request_type = request_type
        self.champ_data = requests.get('http://ddragon.leagueoflegends.com/cdn/10.10.3208608/data/en_US/'
                                       'champion.json').json()['data']

    def save(self, league=False, games=False, state=None):
        """write the instance data in .league or .games to its respective file bu setting it to True"""
        if league:
            with open(LEAGUE_FP, 'w') as f:
                json.dump(self.league, f, indent=4)
                print(f'\033[94msaved {LEAGUE_FP}\033[0m')

        if games:
            with open(GAMES_FP, 'w') as f2:
                json.dump(self.games, f2, indent=4)
                print(f'\033[94msaved {GAMES_FP}\033[0m')

        if state:  # save some data from an AR
            self.erred.update(state.erred)

    def champ_by_id(self, champ_id):
        for champ in self.champ_data:
            cid = int(self.champ_data[champ]['key'])
            if cid == champ_id:
                return champ

    def update_summoner(self, args):
        """takes a list of IGN's and requests summoner data for each
        saves it to silverfantasy.json. returns raw resp."""
        id_ar = AsyncRequester()
        resp = []

        for s_ign in args:
            if (AsyncRequester.t_req + id_ar.c_req) % REQ_PER_SEC == 0 and id_ar.c_req > 0:  # rate limit
                resp += id_ar.run()
                time.sleep(1)
            id_ar.sum_dat(s_ign)
        # id_ar.__floor__()
        resp += id_ar.run()

        for player in resp:
            if 'status' in player:  # skip errors
                continue

            try:
                self.league["PLAYERS"][player["name"].lower()]['dat'] = player
            except KeyError:
                self.league["PLAYERS"][player["name"].lower()] = {}
                self.league["PLAYERS"][player["name"].lower()]['dat'] = player

        self.save(league=True, state=id_ar)

        ret = {"resp": resp, "err": self.erred}
        return ret

    def check_ids(self, igns: list, id_type='id', request=True):
        """take list of igns, returns dict of ign: id_type
        UPDATES LOCAL BUT DOES NOT SAVE"""
        ids = {}
        to_request = []

        for ign in igns:
            if ign in self.league["PLAYERS"]:
                ids[ign] = self.league["PLAYERS"][ign]['dat'][id_type]
            else:
                to_request.append(ign)

        if request and to_request:  # request id's for the ign's not found locally. skip errors.
            resp = self.update_summoner(to_request)['resp']
            for s in resp:
                if 'status' not in s:
                    ids[s["name"]] = s[id_type]

        return ids

    def update_ranked(self, args):
        """takes in a list of IGN's and returns season ranked data. may need to get id's - uses [id] aka summoner id
        UPDATES AND SAVES LOCAL"""
        rank_ar = AsyncRequester()
        _ids = self.check_ids(args)
        resp = []

        for sid in _ids:
            rank_ar.ranked(_ids[sid])
            if (AsyncRequester.t_req + rank_ar.c_req) % REQ_PER_SEC == 0:
                resp += rank_ar.run()
                time.sleep(1)

        resp += rank_ar.run()
        for ranked_dat in resp:  # for all the players' ranked data
            for stats in ranked_dat:  # for the diff queues (max 3; solo, flex, TFT)
                if stats['queueType'] == 'RANKED_SOLO_5x5':
                    player = stats
                    rank = player["tier"] + ' ' + player["rank"]
                    n = player["wins"] + player["losses"]
                    wr = player["wins"] / n
                    cost = 50 + (n/(n+50))*((wr*100)-50) + (lin_mmr_dict[rank]/400)

                    # assign local values
                    c_player = self.league["PLAYERS"][player["summonerName"].lower()]  # literally has to exist!
                    c_player["rank"] = rank
                    c_player["inactive"] = player["inactive"]
                    c_player["wr"] = round(100 * wr, 2)
                    c_player["games"] = n
                    c_player["leagues"] = [] if "leagues" not in c_player else c_player["leagues"]
                    c_player["wr mod"] = round(cost, 2)
                    c_player["lp"] = player['leaguePoints']
                    c_player["teams"] = [] if "teams" not in c_player else c_player["teams"]

        self.save(league=True, state=rank_ar)
        ret = {"resp": resp, "err": self.erred}  # hack resp in to a JSON-able, change ret later to what trey wants
        return ret
    
    def request_weekly_soloq(self, args):
        """takes in a bunch of summoners and returns matches to be requested.
        does NOT save or update internally"""
        hist_ar = AsyncRequester()
        aids_dict = self.check_ids(args, 'accountId')  # lol AIDS
        to_request = []
        resp = []

        for ign in aids_dict:
            aid = aids_dict[ign]
            hist_ar.match_history(aid, queries={"beginTime": last_friday(), "queue": 420})
            if (AsyncRequester.t_req + hist_ar.c_req) % 20 == 0:
                resp += hist_ar.run()
                time.sleep(1)
        resp += hist_ar.run()  # get the match histories

        errors = 0
        for hist in resp:  # PROBABLY BROKEN
            if 'status' not in hist:  # ignore all errors
                for match in hist["matches"]:
                    if str(match['gameId']) not in self.games:
                        to_request.append(match['gameId'])
            else:
                errors += 1

        self.save(state=hist_ar, league=True)
        return to_request

    def _get_registered_pids(self, raw_game):
        """take a raw match-by-id API response and gets participant id's for registered players"""
        pid = {}
        for p in raw_game["participantIdentities"]:
            ign = p['player']['summonerName'].lower()
            if ign in self.league["PLAYERS"]:
                pid[ign] = p['participantId']
                try:  # save the game in the players match history
                    if raw_game['gameId'] not in self.league["PLAYERS"][ign]['history']:
                        self.league["PLAYERS"][ign]['history'].append(raw_game['gameId'])
                except KeyError:
                    self.league["PLAYERS"][ign]['history'] = [raw_game['gameId']]

        return pid

    def update_matches(self, args):
        """takes in summoners and updates matches, save ALL! return updated matches."""
        to_get = self.request_weekly_soloq(args)
        if not to_get:
            return {'resp': None, 'err': self.erred}

        match_ar = AsyncRequester()
        resp = []

        i = 0  # count the number of times it's run (every 20 req / 1 sec)
        # RATE LIMITING IMPLEMENTED HERE - 20 / SEC & 100 / 90 + 5 SEC
        for mid in to_get:
            match_ar.match(mid)
            if (AsyncRequester.t_req + match_ar.__floor__().c_req) % REQ_PER_SEC == 0:
                resp += match_ar.run()  # run
                time.sleep(1)  # then wait a sec
                i += 1
                if i % 5 == 0:  # 100 req / 90 (120?) sec
                    print('RATE LIMIT EXCEEDED - SLEEPING')
                    time.sleep(90)
        resp += match_ar.run()

        # CHANGING EVERYTHING: games will now be stored at a SURFACE level without repeats. NOT under players.
        # PLAYER dicts will still exist while this is under development.
        ret = {}  # return variable indexes game by id
        for game in resp:
            if 'status' in game:  # skip errors
                continue

            matched = self._get_registered_pids(game)  # get riot's dumb participant id's
            self.games[game['gameId']] = {} if game['gameId'] not in self.games else self.games[game['gameId']]

            for player, pid in matched.items():
                part = game['participants'][pid-1]
                stats = part['stats']

                # CALCULATE (MAKE THIS ITS OWN CLASS)
                duration = game['gameDuration']
                kills = stats["kills"]
                deaths = stats["deaths"]
                assists = stats["assists"]
                csm = (stats['neutralMinionsKilled'] + stats['totalMinionsKilled']) / (duration / 60)
                team = part['teamId']
                tk, td, ta = 0, 0, 0  # team kills, assists, deaths
                for sumr in game["participants"]:
                    if sumr["teamId"] == team:
                        tk += sumr["stats"]["kills"]
                        td += sumr["stats"]["deaths"]
                        ta += sumr["stats"]["assists"]
                kp = (kills + assists) / tk if tk > 0 else 1
                dp = deaths / td if td > 0 else 0
                vpm = stats['visionScore'] / (duration / 60)
                points = (kills + .75 * assists - deaths) * (0.9 + kp / 5) + csm + 3 * vpm

                # WRITE
                c_game = self.games[game['gameId']]
                c_game.update({player: {"pid": pid,
                                        "score": round(points, 2),
                                        "champ": get_champ(part['championId']),
                                        "kda": (kills, deaths, assists),
                                        "duration": duration,
                                        "csm": round(csm, 2),
                                        "team": team,
                                        "kp": round(100*kp, 2),
                                        "dp": round(100*dp, 2),
                                        "vpm": round(vpm, 2)
                                        }})  # create player dicts within the game
                ret[game['gameId']] = c_game

        self.save(league=True, games=True, state=match_ar)
        ret = {"resp": resp, "err": self.erred}
        return ret

    def avg_by_queue(self, args):
        print(args)
        return {'status': 200}

    def run(self, args):
        """for running"""
        if self.request_type == "summoner":
            return self.update_summoner(args)
        elif self.request_type == "ranked":
            return self.update_ranked(args)
        elif self.request_type == "matches":
            return self.update_matches(args)
        elif self.request_type == "avg":
            return self.avg_by_queue(args)
        elif self.request_type == "ABC":
            return f'ABSTRACT BASE CLASS'
        else:
            print(f'\033[93mERROR: UNKNOWN REQUEST TYPE {self.request_type}\033[0m')


if __name__ == "__main__":
    u = Updater('matches')  # doesn't even matter how i initialize it
    master_list = [p for p in u.league["PLAYERS"]]
    print(u.update_matches(master_list))
