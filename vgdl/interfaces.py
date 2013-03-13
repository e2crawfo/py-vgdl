'''
Created on 2013 2 18

@author: Tom Schaul (schaul@gmail.com)

Wrappers for games to interface them with artificial players.
These are based on the PyBrain RL framework of Environment and Task classes.
'''

from numpy import zeros
import pygame    

from pybrain.rl.environments.environment import Environment
from pybrain.rl.environments.episodic import EpisodicTask
from pybrain.rl.agents.agent import Agent
from pybrain.rl.learners.modelbased import policyIteration
from pybrain.utilities import drawIndex, setAllArgs #, crossproduct

from ontology import RotatingAvatar, BASEDIRS, GridPhysics, LinkAvatar, kill_effects
from core import VGDLSprite, Avatar
from tools import listRotate



        
class StateObsHandler(object):
    """ Managing different types of state representations,
    and of observations. 
    
    A state is always composed of a tuple, with the avatar position (x,y) in the first places.
    If the avatar orientation matters, the orientation is the third element of the tuple. 
    """
    
    # is the avatar having an orientation or not?
    orientedAvatar = False
    
    # is the avatar a single persistent sprite, or can it be transformed?
    uniqueAvatar = True
    
    # can the avatar die?
    mortalAvatar = False
    
    # can other sprites die?
    mortalOther = False
    
    # can other sprites move
    staticOther = True
    
    def __init__(self, game, **kwargs):
        setAllArgs(self, kwargs)
        self._game = game
        self._avatar_types = []
        self._abs_avatar_types = []
        self._other_types = []
        self._mortal_types = []
        for skey in sorted(game.sprite_constr): 
            sclass, _, stypes = game.sprite_constr[skey]
            if issubclass(sclass, Avatar):
                self._abs_avatar_types += stypes[:-1]
                self._avatar_types += [stypes[-1]]
                if issubclass(sclass, RotatingAvatar) or issubclass(sclass, LinkAvatar):
                    self.orientedAvatar = True
            if skey not in game.sprite_groups:
                continue 
            ss = game.sprite_groups[skey]
            if len(ss) == 0:
                continue
            if isinstance(ss[0], Avatar):
                assert issubclass(ss[0].physicstype, GridPhysics), \
                        'Not supported: Game must have grid physics, has %s'\
                        % (self._avatar.physicstype.__name__)                       
            else:
                self._other_types += [skey]
                if not ss[0].is_static:
                    self.staticOther = False
        assert self.staticOther, "not yet supported: all non-avatar sprites must be static. "
        
        self._avatar_types = sorted(set(self._avatar_types).difference(self._abs_avatar_types))
        self.uniqueAvatar = (len(self._avatar_types) == 1)
        #assert self.uniqueAvatar, 'not yet supported: can only have one avatar class'
        
        # determine mortality
        for skey, _, effect, _ in game.collision_eff:
            if effect in kill_effects:
                if skey in self._avatar_types+self._abs_avatar_types:
                    self.mortalAvatar = True
                if skey in self._other_types:
                    self.mortalOther = True
                    self._mortal_types += [skey]
        
                 
        # retain observable features, and their colors
        self._obstypes = {}
        self._obscols = {}
        for skey in self._other_types:
            ss = game.sprite_groups[skey]
            self._obstypes[skey] = [self._sprite2state(sprite, oriented=False) 
                                    for sprite in ss if sprite.is_static]
            self._obscols[skey] = ss[0].color            
        
        if self.mortalOther:
            self._gravepoints = {}
            for skey in self._mortal_types:
                for s in self._game.sprite_groups[skey]:
                    self._gravepoints[(skey, self._rect2pos(s.rect))] = True
         
    @property
    def _avatar(self):
        ss = self._game.getAvatars()
        assert len(ss) <= 1, 'Not supported: Only a single avatar can be used, found %s' % ss
        if len(ss) == 0:
            return None
        return ss[0]
    
    def setState(self, state):
        # no avatar?
        if self._avatar is None:
            pos = (state[0]*self._game.block_size, state[1]*self._game.block_size)
            if self.uniqueAvatar:
                atype = self._avatar_types[0]
            else:
                atype = state[-1]
            self._game._createSprite([atype], pos)
        
        # bad avatar?
        if not self.uniqueAvatar:
            atype = state[-1]
            if self._avatar.name != atype:
                self._game.kill_list.append(self._avatar)
                pos = (state[0]*self._game.block_size, state[1]*self._game.block_size)
                self._game._createSprite([atype], pos)            
            
        if self.visualize:
            self._avatar._clear(self._game.screen, self._game.background)
        if not self.uniqueAvatar:
            state = state[:-1]
        if self.mortalOther:
            self._setPresences(state[-1])
            state = state[:-1]  
        self._setSpriteState(self._avatar, state)
        self._game._clearAll(self.visualize)
        self._avatar.lastrect = self._avatar.rect
        self._avatar.lastmove = 0               
        
    def getState(self):        
        if self._avatar is None:
            return (-1,-1, 'dead')
        if self.mortalOther:
            if self.uniqueAvatar:
                return tuple(list(self._sprite2state(self._avatar)) + [self._getPresences()])
            else:
                return tuple(list(self._sprite2state(self._avatar)) 
                             + [self._getPresences()] + [self._avatar.name])
        else:
            if self.uniqueAvatar:
                return self._sprite2state(self._avatar)
            else:
                return tuple(list(self._sprite2state(self._avatar)) 
                             + [self._avatar.name])
                
    def _getPresences(self):
        """ Binary vector of which non-avatar sprites are present. """
        res = zeros(len(self._gravepoints), dtype=int)
        for i, (skey, pos) in enumerate(sorted(self._gravepoints)):
            if pos in [self._rect2pos(s.rect) for s in self._game.sprite_groups[skey]
                       if s not in self._game.kill_list]:
                res[i] = 1                
        return tuple(list(res))
    
    def _setPresences(self, p):
        for i, (skey, pos) in enumerate(sorted(self._gravepoints)):
            target = p[i] != 0 
            matches = [s for s in self._game.sprite_groups[skey] if self._rect2pos(s.rect)==pos]
            current = (not len(matches) == 0 and matches[0] not in self._game.kill_list)
            if current == target:
                continue
            elif current:
                #print 'die', skey, pos, matches
                self._game.kill_list.append(matches[0])
            elif target:
                #print 'live', skey, pos, matches
                pos = (pos[0]*self._game.block_size, pos[1]*self._game.block_size)
                self._game._createSprite([skey], pos)
                    
    def _rawSensor(self, state):
        return [(state in ostates) for _, ostates in sorted(self._obstypes.items())[::-1]]
    
    def _sprite2state(self, s, oriented=None):
        pos = self._rect2pos(s.rect)
        if oriented is None and self.orientedAvatar:
            return (pos[0], pos[1], s.orientation)
        else:
            return pos
        
    def _rect2pos(self, r):
        return (r.left / self._game.block_size, r.top / self._game.block_size)
    
    def _setRectPos(self, s, pos):
        s.rect = pygame.Rect((pos[0] * self._game.block_size,
                              pos[1] * self._game.block_size),
                             (self._game.block_size, self._game.block_size))
        
    def _setSpriteState(self, s, state):
        if self.orientedAvatar:
            s.orientation = state[2]
        self._setRectPos(s, (state[0], state[1]))
        
    def _stateNeighbors(self, state):
        """ Can be different in subclasses... 
        
        By default: current position and four neighbors. """
        pos = (state[0], state[1])
        ns = [(a[0] + pos[0], a[1] + pos[1]) for a in BASEDIRS]
        if self.orientedAvatar:
            # subjective perspective, so we rotate the view according to the current orientation
            ns = listRotate(ns, BASEDIRS.index(state[2]))
            return ns
        else:
            return ns
        
    
    

class GameEnvironment(Environment, StateObsHandler):
    """ Wrapping a VGDL game into an environment class, where state can be read out directly
    or set. Currently limited to single avatar games, with gridphysics, 
    where all other sprites are static. 
    """
    
    # If the visualization is enabled, all actions will be reflected on the screen.
    visualize = False
    
    # In that case, optionally wait a few milliseconds between actions?
    actionDelay = 0
    
    # Recording events (in slightly redundant format state-action-nextstate)
    recordingEnabled = False
    
    def __init__(self, game, actionset=BASEDIRS, **kwargs):
        StateObsHandler.__init__(self, game, **kwargs)
        self._actionset = actionset
        self._initstate = self.getState()
        ns = self._stateNeighbors(self._initstate)
        self.outdim = (len(ns) + 1) * len(self._obstypes)
        self.reset()                
    
    def reset(self):
        if self.visualize:
            self._game._initScreen(self._game.screensize)
        self.setState(self._initstate)
        self._game.kill_list = []
        if self.visualize:
            pygame.display.flip()    
        if self.recordingEnabled:
            self._last_state = self.getState()
            self._allEvents = []                
    
    def getSensors(self, state=None):
        if state is None:
            state = self.getState()
        if self.orientedAvatar:
            pos = (state[0], state[1])
        else:
            pos = state 
        res = zeros(self.outdim)
        ns = [pos] + self._stateNeighbors(state)
        for i, n in enumerate(ns):
            os = self._rawSensor(n)
            res[i::len(ns)] = os
        return res
        
    def performAction(self, action, onlyavatar=False):
        """ Action is an index for the actionset.  """
        if action is None:
            return   
        # take action and compute consequences
        self._avatar._readMultiActions = lambda * x: [self._actionset[action]]        

        if self.visualize:
            self._game._clearAll(self.visualize)            

        # update sprites 
        if onlyavatar:
            self._avatar.update(self._game)
        else:
            for s in self._game:
                s.update(self._game)
        
        # handle collision effects                
        self._game._updateCollisionDict()
        self._game._eventHandling()
        self._game._clearAll(self.visualize)
        
        # update screen
        if self.visualize:
            self._game._drawAll()                            
            pygame.display.update(VGDLSprite.dirtyrects)
            VGDLSprite.dirtyrects = []
            pygame.time.wait(self.actionDelay)       
                       

        if self.recordingEnabled:
            self._previous_state = self._last_state
            self._last_state = self.getState()
            self._allEvents.append((self._previous_state, action, self._last_state))
            
    def _isDone(self):
        # remember reward if the final state ends the game
        for t in self._game.terminations[1:]: 
            # Convention: the first criterion is for keyboard-interrupt termination
            ended, win = t.isDone(self._game)
            if ended:
                return ended, win
        return False, False

    def rollOut(self, action_sequence, init_state=None, callback=lambda * _:None):
        """ Take a sequence of actions. """
        if init_state is not None:
            self.setState(init_state)
        for a in action_sequence:
            if self._isDone()[0]:
                break
            self.performAction(a)
            callback(self)
        

class GameTask(EpisodicTask):
    """ A minimal Task wrapper that only considers win/loss information. """
    _ended = False
    
    maxSteps=100
    
    def reset(self):
        self.env.reset()
        self._ended = False
        
    def getReward(self):
        self._ended, win = self.env._isDone()
        if self._ended:
            if win:
                return 1
            else:
                return -1
        return 0
    
    def isFinished(self):
        return self._ended or self.samples >= self.maxSteps


class InteractiveAgent(Agent):
    """ Reading key commands from the user. """
       
    def getAction(self):
        from pygame.locals import K_LEFT, K_RIGHT, K_UP, K_DOWN
        from pygame.locals import K_ESCAPE, QUIT        
        from ontology import RIGHT, LEFT, UP, DOWN
        pygame.event.pump()
        keystate = pygame.key.get_pressed()    
        res = None
        if   keystate[K_RIGHT]: res = BASEDIRS.index(RIGHT)
        elif keystate[K_LEFT]:  res = BASEDIRS.index(LEFT)
        elif keystate[K_UP]:    res = BASEDIRS.index(UP)
        elif keystate[K_DOWN]:  res = BASEDIRS.index(DOWN)        
        if keystate[K_ESCAPE] or pygame.event.peek(QUIT):
            raise 'User aborted.'
        return res
    

class PolicyDrivenAgent(Agent):
    """ Taking actions according to a (possibly stochastic) policy that has 
    full state information (state index). """
    
    def __init__(self, policy, stateIndexFun):
        self.policy = policy
        self.stateIndexFun = stateIndexFun
    
    def getAction(self):
        return drawIndex(self.policy[self.stateIndexFun()])
            
    @staticmethod
    def buildOptimal(game_env, discountFactor=0.99):
        """ Given a game, find the optimal (state-based) policy and 
        return an agent that is playing accordingly. """
        from mdpmap import MDPconverter
        C = MDPconverter(env=game_env)
        Ts, R, _ = C.convert()
        policy, _ = policyIteration(Ts, R, discountFactor=discountFactor)
        def x(*_):
            s = game_env.getState()
            #print s
            i = C.states.index(s)
            return i
        #return PolicyDrivenAgent(policy, lambda *_: C.states.index(game_env.getState()))
        return PolicyDrivenAgent(policy, x)


def makeGifVideo(game, actions, initstate=None, prefix='seq_', duration=0.1,
                 outdir='../gifs/', tmpdir='../temp/'):
    """ Generate an animated gif from a sequence of actions. """
    from external_libs.images2gif import writeGif
    import Image 
    env = GameEnvironment(game, visualize=True)
    if initstate is not None:
        env.setState(initstate)
    env._counter = 1
    res_images = []
    astring = ''.join([str(a) for a in actions if a is not None])
    
    def cb(*_):
        fn = tmpdir + "tmp%05d.png" % env._counter
        pygame.image.save(game.screen, fn)
        res_images.append(Image.open(fn))
        env._counter += 1
        
    env.rollOut(actions, callback=cb)
    writeGif(outdir + prefix + '%s.gif' % astring, res_images, duration=duration, dither=0)
    
    

def testRollout(actions=[0, 0, 2, 2, 0, 3] * 20):        
    from examples.gridphysics.mazes import polarmaze_game, maze_level_1
    from core import VGDLParser
    game_str, map_str = polarmaze_game, maze_level_1
    g = VGDLParser().parseGame(game_str)
    g.buildLevel(map_str)    
    env = GameEnvironment(g, visualize=True, actionDelay=100)
    env.rollOut(actions)
        
    
def testRolloutVideo(actions=[0, 0, 2, 2, 0, 3] * 2):        
    from examples.gridphysics.mazes import polarmaze_game, maze_level_1
    from core import VGDLParser
    game_str, map_str = polarmaze_game, maze_level_1
    g = VGDLParser().parseGame(game_str)
    g.buildLevel(map_str)
    makeGifVideo(g, actions)
    
    
def testInteractions():
    from random import randint
    from pybrain.rl.experiments.episodic import EpisodicExperiment
    from core import VGDLParser
    from examples.gridphysics.mazes import polarmaze_game, maze_level_1
    
    class DummyAgent(Agent):
        total = 4
        def getAction(self):
            res = randint(0, self.total - 1)
            return res    
        
    game_str, map_str = polarmaze_game, maze_level_1
    g = VGDLParser().parseGame(game_str)
    g.buildLevel(map_str)
    
    env = GameEnvironment(g, visualize=True, actionDelay=100)
    task = GameTask(env)
    agent = DummyAgent()
    exper = EpisodicExperiment(task, agent)
    res = exper.doEpisodes(2)
    print res

def testPolicyAgent():
    from pybrain.rl.experiments.episodic import EpisodicExperiment
    from core import VGDLParser
    from examples.gridphysics.mazes import polarmaze_game, maze_level_2
        
    game_str, map_str = polarmaze_game, maze_level_2
    g = VGDLParser().parseGame(game_str)
    g.buildLevel(map_str)
    
    env = GameEnvironment(g, visualize=True, actionDelay=100)
    task = GameTask(env)
    agent = PolicyDrivenAgent.buildOptimal(env)
    exper = EpisodicExperiment(task, agent)
    res = exper.doEpisodes(2)
    print res
    
def testRecordingToGif(human=False):
    from pybrain.rl.experiments.episodic import EpisodicExperiment
    from core import VGDLParser
    from examples.gridphysics.mazes import polarmaze_game, maze_level_2
        
    game_str, map_str = polarmaze_game, maze_level_2
    g = VGDLParser().parseGame(game_str)
    g.buildLevel(map_str)
    env = GameEnvironment(g, visualize=human, recordingEnabled=True, actionDelay=200)
    task = GameTask(env)
    if human:
        agent = InteractiveAgent()
    else:
        agent = PolicyDrivenAgent.buildOptimal(env)
    exper = EpisodicExperiment(task, agent)
    res = exper.doEpisodes(1)
    print res
    
    actions = [a for _,a,_ in env._allEvents]
    makeGifVideo(g, actions, initstate=env._initstate)
    
def testAugmented():
    from core import VGDLParser
    from pybrain.rl.experiments.episodic import EpisodicExperiment
    from mdpmap import MDPconverter
    
    miniz= """
wwwwwwwwwwwwwww
wA  + k  1 0 Gw
ww1wwwww wwwwww
ww   1   wwwwww
wwwwwwwwwwwwwww
"""


    zelda_level2 = """
wwwwwwwwwwwww
wwwwwk1wwwwww
wwwwww   A ww
wwwww  www +w
wwwww1wwwwwww
wwwww0Gwwwwww
wwwwwwwwwwwww
"""

    rigidzelda_game2 = """
BasicGame frame_rate=10
    SpriteSet     
        structure > Immovable
            goal   > color=GREEN
            door   > color=LIGHTGREEN
            key    > color=YELLOW     
            sword  > color=RED
            monster > color=ORANGE
        slash  > Flicker limit=5  singleton=True
        avatar  > MovingAvatar 
            naked   > 
            nokey   > color=RED
            withkey > color=YELLOW
    LevelMapping
        G > goal
        k > key        
        + > sword
        A > naked
        0 > door
        1 > monster            
    InteractionSet
        avatar wall    > stepBack
        nokey door     > stepBack
        goal avatar    > killSprite        
        monster nokey  > killSprite        
        naked monster  > killSprite
        withkey monster> killSprite
        key  avatar    > killSprite
        sword avatar   > killSprite
        nokey key   > transformTo stype=withkey
        naked sword > transformTo stype=nokey                
    TerminationSet
        SpriteCounter stype=goal   limit=0 win=True
        SpriteCounter stype=avatar limit=0 win=False              
"""
    from examples.gridphysics.mazes.rigidzelda import rigidzelda_game, zelda_level
    g = VGDLParser().parseGame(rigidzelda_game)
    g.buildLevel(zelda_level)
    #g.buildLevel(miniz)
    env = GameEnvironment(g, visualize=False, 
                          recordingEnabled=True, actionDelay=150)
    C = MDPconverter(g, env=env, verbose=True)
    Ts, R, _ = C.convert()
    print C.states
    print Ts[0]
    print R
    env.reset()
    agent = PolicyDrivenAgent.buildOptimal(env)
    env.visualize = True
    env.reset()
    task = GameTask(env)    
    exper = EpisodicExperiment(task, agent)
    res = exper.doEpisodes(1)
    
    
if __name__ == "__main__":
    #testRollout()
    # testInteractions()
    #testRolloutVideo()
    #testPolicyAgent()
    #testRecordingToGif(human=True)

    testAugmented()
