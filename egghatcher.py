#!/usr/bin/env python3.7
import argparse
import re
import asyncio
import logging
import re
from sys import platform
import time

from PIL import Image
import sys
from pyocr import pyocr
from pyocr import builders
import yaml

from pokemonlib import PokemonGo

from colorlog import ColoredFormatter

logger = logging.getLogger('ivcheck')
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = ColoredFormatter("  %(log_color)s%(levelname)-8s%(reset)s | %(log_color)s%(message)s%(reset)s")
ch.setFormatter(formatter)
logger.addHandler(ch)

# Time to stay on eggs and world
TIME_ON_EGGS = 240
TIME_ON_WORLD = 15

def get_median_location(box_location):
    '''
    Given a list of 4 coordinates, returns the central point of the box
    '''
    x1, y1, x2, y2 = box_location
    return [int((x1 + x2) / 2), int((y1 + y2) / 2)]


class Main:
    def __init__(self, args):
        with open(args.config, "r") as f:
            self.config = yaml.load(f)
        self.args = args
        tools = pyocr.get_available_tools()
        self.tool = tools[0]
        self.state = ''

    async def tap(self, location):
        coordinates = self.config['locations'][location]
        if len(coordinates) == 2:
            await self.p.tap(*coordinates)
            if location in self.config['waits']:
                await asyncio.sleep(self.config['waits'][location])
        elif len(coordinates) == 4:
            median_location = get_median_location(coordinates)
            await self.p.tap(*median_location)
            if location in self.config['waits']:
                await asyncio.sleep(self.config['waits'][location])
        else:
            logger.error('Something is not right.')
            raise Exception

    async def key(self, keycode):
        await self.p.key(keycode)
        if str(keycode).lower in self.config['waits']:
            await asyncio.sleep(self.config['waits'][str(keycode).lower])

    async def swipe(self, location, duration):
        await self.p.swipe(
            self.config['locations'][location][0],
            self.config['locations'][location][1],
            self.config['locations'][location][2],
            self.config['locations'][location][3],
            duration
        )
        if location in self.config['waits']:
            logger.info('Waiting ' + str(self.config['waits'][location]) + ' seconds after ' + str(self.config['locations'][location]) + '...')
            await asyncio.sleep(self.config['waits'][location])

    async def cap_and_crop(self, box_location):
        screencap = await self.p.screencap()
        crop = screencap.crop(self.config['locations'][box_location])
        text = self.tool.image_to_string(crop).replace("\n", " ")
        logger.debug('[OCR] Found text: ' + text)
        return text

    async def switch_app(self):
        logger.info('Switching apps...')
        await self.key('APP_SWITCH')
        await self.tap('second_app_position')

    async def get_current_state(self, screencap):
        text_eggs = screencap.crop(self.config['locations']['eggs_label_box'])
        text_eggs = self.tool.image_to_string(text_eggs).replace("\n", " ")
        text_oh = screencap.crop(self.config['locations']['oh_hatching_box'])
        text_oh = self.tool.image_to_string(text_oh).replace("\n", " ")
        text_gps = screencap.crop(self.config['locations']['im_a_passenger_button_box'])
        text_gps = self.tool.image_to_string(text_gps).replace("\n", " ")

        if 'EGGS' in text_eggs:
            return 'on_eggs'
        elif 'Oh' in text_oh or '?' in text_oh:
            return 'on_hatching'
        elif 'PASSENGER' in text_gps:
            await self.deal_with_blocking_dialogs()
        else:
            return 'on_world'

    async def deal_with_blocking_dialogs(self):
        logger.error('I smell sketchiness! >.<')
        await self.tap('im_a_passenger_button_box')

    async def stop_pokemon_goplus(self, how_long):
        logger.error('Lets stop pokepoke and get some items back')
        await self.tap('pokeball_button')
        await self.tap('settings_button')
        await self.swipe('swipe_to_bottom', 300)
        await self.swipe('swipe_to_bottom', 500)
        await self.tap('pokemon_go_plus_button')
        await self.tap('nearby_pokemon_button')
        logger.info('Oh now we wait for ' + str(int(how_long / 60)) + ' minutes to refill this crappy backpack!')
        await asyncio.sleep(how_long)
        await self.tap('nearby_pokemon_button')
        logger.info("There, that should be good, i'm tired already.... Back to MY EGGS!")
        await self.tap('pokeball_button')
        await self.tap('pokeball_button')

    async def incubate_a_fucking_egg(self):
        # click first egg
        await self.tap('first_egg_distance_box')
        text = await self.cap_and_crop('incubate_button_box')

        if 'INCUBATE' in text:
            logger.warning('The first egg was not incubated yet!')

            # check first incubator, if it has 'USES', it's a bought one, so skip it
            await self.tap('incubate_button_box')
            text = await self.cap_and_crop('incubator_uses_left_box')
            text = str(text).strip()
            if text or 'USE' in text:
                # got paid incubator
                logger.critical('what? ' + text + '???! ....  THIS INCUBATOR IS EXPENSIVE! OH NO, NO, NO!')
                await self.tap('pokeball_button')
                await self.tap('pokeball_button')
            else:
                # got nothing, which probably means
                logger.warning('Incubating first egg...')
                await self.tap('incubator_uses_left_box')
        # otherwise, egg is currently being incubated
        else:
            logger.info('This egg is already being incubated!')
            await self.tap('pokeball_button')

    async def watch_the_egg_hatch(self):
        logger.critical('FINALLY THIS FREAKING EGG JUST HATCHED!')
        # click anywhere, twice (we click on i'm a passenger button)
        await self.tap('im_a_passenger_button_box')
        await self.tap('im_a_passenger_button_box')
        # wait animation
        await asyncio.sleep(20)
        # close pokemon screen
        await self.tap('pokeball_button')

        await self.check_my_eggs()

    async def check_my_eggs(self):
        logger.warning("MY EGGS! \n               ... Gotta Check 'em All! ♫ ... (wait, wut)")

        # opens the eggs list
        await self.tap('pokeball_button')
        await self.tap('pokémon_list_button')
        await self.tap('eggs_tab')

        # gets the egg info
        text = await self.cap_and_crop('first_egg_distance_box')

        # mumbo jumbo for getting the correct distance
        #           "now with regex"
        match = re.match(r'^([0-9SO\.]+)[^0-9SO\.]+([0-9SO\.]+)[^0-9SO\.]*$', text)
        try:
            distance_walked = float(match.group(1).replace('S', '5').replace('O', '0'))
            distance_total = float(match.group(2).replace('S', '5').replace('O', '0'))
            # distance_walked, distance_total = [float(d) for d in text.replace('km', '').split('/')]
        except:
            logger.critical("Oh crap, I don't understand what's going on! (Got \"" + text + '")')
            return False
        else:
            if distance_walked > distance_total:
                logger.debug("It seems that you walked more than the total ammount... Lemme fix that...")
                distance_walked /= 10
            if distance_walked > distance_total:
                logger.error("Well now I don't know what to do... fuck this.")
                await self.tap('pokeball_button')
                return False

        logger.info('You have "walked" {}km so far for this {}km egg'.format(distance_walked, distance_total))

        # if 0km walked, and distances are different,
        # means we are not currently hatching the egg
        if distance_walked == 0 and distance_walked < distance_total:
            await self.incubate_a_fucking_egg()

        # if the distances are the same and equal to zero
        # means that the egg actually just hatched
        elif distance_walked == distance_total == 0:
            await self.check_my_eggs()
            self.state = 'on_hatching'

        await self.tap('pokeball_button')
        return True


    async def start(self):
        self.p = PokemonGo()
        await self.p.set_device(self.args.device_id)
        logger.error('Oh.. eggy eggy eggies...')

        # forces the first round to do the checks and switching
        last_check_time = time.time() - self.config['times']['on_world']
        last_switch_time = time.time()# - self.config['times']['on_each_app']
        last_refill_time = time.time()# - self.config['times']['on_each_app']

        while True:
            screencap = await self.p.screencap()
            self.state = await self.get_current_state(screencap)
            time_now = time.time()

            if self.state == 'on_hatching':
                await self.watch_the_egg_hatch()
            elif self.state == 'on_world':
                pass
            elif self.state == 'on_eggs':
                await self.tap('pokeball_button')
            else:
                # wtf... a gps or weather dialog perhaps?
                await self.deal_with_blocking_dialogs()
                continue

            if args.refill and time_now - last_refill_time >= self.config['times']['refill_each'] and self.state == 'on_world':
                await self.stop_pokemon_goplus(120)
                last_refill_time = time_now
                # if await self.stop_pokemon_goplus(120):
                #     last_refill_time = time_now
                # else:
                #     await self.deal_with_blocking_dialogs()

            if self.args.switch and self.state == 'on_world':
                if time_now - last_switch_time >= self.config['times']['on_each_app']:
                    logger.warning('OK, TIME TO CHECK OUR FRIEND!')
                    await self.switch_app()
                    last_switch_time = time_now
                    last_check_time = time.time() - self.config['times']['on_world']
                    continue

            if time_now - last_check_time >= self.config['times']['on_world'] and self.state == 'on_world':
                # if we spent more than allowed on the world
                #   check the freaking eggs
                if await self.check_my_eggs():
                    last_check_time = time_now
                else:
                    await self.deal_with_blocking_dialogs()


            await asyncio.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pokemon go renamer')
    parser.add_argument('--device-id', type=str, default=None,
                        help="Optional, if not specified the phone is automatically detected. Useful only if you have multiple phones connected. Use adb devices to get a list of ids.")
    parser.add_argument('--config', type=str, default='config.yaml',
                        help="Config file location.")
    parser.add_argument('--switch', type=bool, nargs='?', const=True, default=False,
                        help="Periodically switches between two parallel running instances, to hatch two different accounts simultaneously.")
    parser.add_argument('--refill', type=bool, nargs='?', const=True, default=False,
                        help="Periodically goes to the menu and disables pokemon catch to get more items for a while.")
    args = parser.parse_args()

    asyncio.run(Main(args).start())
