import logging
from ...pcc.recursivedescent import RecursiveDescentParser
from . import nodes


class CParser(RecursiveDescentParser):
    """ C Parser.

    Implemented in a recursive descent way, like the CLANG[1]
    frontend for llvm, also without the lexer hack[2]. See for the gcc
    c parser code [3].

    The clang parser is very versatile, it can handle C, C++, objective C
    and also do code completion. This one is very simple, it can only
    parse C.

    [1] http://clang.org/
    [2] https://en.wikipedia.org/wiki/The_lexer_hack
    [3] https://raw.githubusercontent.com/gcc-mirror/gcc/master/gcc/c/
        c-parser.c
    """
    logger = logging.getLogger('cparser')

    def __init__(self, coptions):
        super().__init__()
        self.coptions = coptions
        self.type_table = {}

    def register_type(self, typ: nodes.NamedType):
        self.type_table[typ.name] = typ

    def fill_type_table(self):
        """ Register some basic known types """
        self.register_type(nodes.IntegerType('int'))
        self.register_type(nodes.IntegerType('char'))
        self.register_type(nodes.FloatingPointType('float'))
        self.register_type(nodes.FloatingPointType('double'))
        self.register_type(nodes.VoidType())

    def parse(self, tokens):
        """ Here the parsing of C is begun ...

        Parse the given tokens.
        """
        self.init_lexer(tokens)
        self.type_table = {}
        self.fill_type_table()
        cu = self.parse_translation_unit()
        self.logger.debug('Parsing finished')
        cu.type_table = self.type_table  # HACK to pass types
        return cu

    def next_token(self):
        """ Advance to the next token """
        tok = super().next_token()
        # print('parse', tok)

        # Implement lexer hack here:
        if tok and tok.typ == 'ID':
            if tok.val in self.type_table:
                tok.typ = 'TYPE-ID'

        # print('parse', tok)
        return tok

    @property
    def peak(self):
        """ Look at the next token to parse without popping it """
        if self.token:
            # Also implement lexer hack here:
            if self.token.typ == 'ID':
                if self.token.val in self.type_table:
                    return 'TYPE-ID'
            return self.token.typ

    # def is_type(self, identifier):
    #     return identifier in self.type_table

    def parse_translation_unit(self):
        """ Top level start of parsing """
        declarations = []
        while not self.at_end:
            for declaration in self.parse_external_declaration():
                declarations.append(declaration)
        return nodes.CompilationUnit(declarations)

    # Declarations part:
    def parse_external_declaration(self):
        return self.parse_function_or_object_decl()

    def parse_function_or_object_decl(self):
        """ Parse a function definition or a list of object declarations """
        ds = self.parse_decl_spec()
        # print(ds)
        return self.parse_decl_group(ds)

    def parse_declaration(self):
        """ Parse normal declaration inside function """
        ds = self.parse_decl_spec()
        # print(ds)
        # TODO: perhaps not parse functions here?
        return self.parse_decl_group(ds)

    def parse_decl_spec(self):
        """ Parse declaration stuff like, static, volatile, int, void, etc.."""
        ds = nodes.DeclSpec()
        while True:
            if self.peak == 'TYPE-ID':
                typ = self.consume()
                if ds.has_type:
                    self.error('Type already defined', typ.loc)
                else:
                    ds.typ = self.type_table[typ.val]
            elif self.peak in ['typedef', 'static', 'extern', 'volatile']:
                storage = self.consume().val
                ds.modifiers.append(storage)
            else:
                break
        return ds

    def parse_decl_group(self, ds):
        """ Parse the rest after the first declaration spec.

        For example we have parsed 'static int' and we will now parse the rest.
        This can be either a function, or a sequence of initializable
        variables. At least it will probably contain some sort of
        identifier and an optional pointer stuff.
        """

        declarations = []
        d = self.parse_declarator(ds)
        if d.is_function and not self.is_decl_following():
            # if function, parse implementation.
            # func_def = None
            body = self.parse_compound_statement()
            d.body = body
            declarations.append(d)
        else:
            # We have variables here
            # print(ds, d)

            declarations.append(d)
            while self.has_consumed(','):
                d = self.parse_declarator(ds)
                declarations.append(d)
                # print(ds, d)
            self.consume(';')
        return declarations

    def is_decl_following(self):
        if self.peak in [',', ';', '=']:
            return True
        return False

    def parse_declarator(self, ds):
        if ds.typ is None:
            self.error("Expected type")
        typ = ds.typ
        while self.peak in ['*', 'volatile']:
            if self.has_consumed('*'):
                typ = nodes.PointerType(typ)
            else:
                self.consume('volatile')
                # TODO: store qualifier?
        return self.parse_direct_declarator(typ)

    def parse_direct_declarator(self, typ):
        # First parse some id, or something else
        is_function = False

        if self.peak == 'ID':
            name = self.consume('ID')
        elif self.peak == '(':
            raise NotImplementedError('special case?')
            self.consume('(')
            self.parse_declarator()
            self.consume(')')
        else:
            raise NotImplementedError(str(self.peak))

        # Now we have name, check for function decl:
        while True:
            if self.peak == '(':
                args = self.parse_function_declarator()
                is_function = True
                arg_types = [ad.typ for ad in args]
                return_type = typ
                # d.typ = ds.typ
                typ = nodes.FunctionType(arg_types, return_type)
            else:
                break

        if is_function:
            d = nodes.FunctionDeclaration(typ, name.val, name.loc)
            d.arguments = args
        else:
            d = nodes.VariableDeclaration(typ, name.val, name.loc)
        assert isinstance(d.typ, nodes.CType), str(d.typ)
        return d

    def parse_function_declarator(self):
        """ Parse function postfix. We have type and name, now parse
            function arguments """
        # TODO: allow K&R style arguments
        args = []
        self.consume('(')
        if self.peak == ')':
            # No arguments..
            self.consume(')')
        else:
            while True:
                ds = self.parse_decl_spec()
                d = self.parse_declarator(ds)
                args.append(d)
                if not self.has_consumed(','):
                    break
            self.consume(')')
        return args

    def parse_function_definition(self):
        """ Parse a function """
        raise NotImplementedError()
        self.parse_compound_statement()

    # Statement part:
    def parse_statement_or_declaration(self):
        """ Parse either a statement or a declaration

        Returns: a list of statements """

        if self.is_declaration_statement():
            statements = self.parse_declaration()
        else:
            statements = [self.parse_statement()]
        return statements

    def is_declaration_statement(self):
        """ Determine whether we are facing a declaration or not """
        if self.peak in ['static', 'volatile', 'TYPE-ID']:
            return True
        if self.peak == 'ID':
            # Check for defined type here
            # TODO
            # raise NotImplementedError()
            return False
        return False

    def parse_statement(self):
        """ Parse a statement """
        m = {
            'for': self.parse_for_statement,
            'if': self.parse_if_statement,
            'do': self.parse_do_statement,
            'while': self.parse_while_statement,
            'switch': self.parse_switch_statement,
            'case': self.parse_case_statement,
            'break': self.parse_break_statement,
            'return': self.parse_return_statement,
            '{': self.parse_compound_statement
            }
        if self.peak in m:
            statement = m[self.peak]()
        else:
            statement = self.parse_expression()
            self.consume(';')
        return statement

    def parse_compound_statement(self):
        """ Parse a series of statements surrounded by '{' and '}' """
        statements = []
        loc = self.consume('{').loc
        while self.peak != '}':
            statements.extend(self.parse_statement_or_declaration())
        self.consume('}')
        return nodes.Compound(statements, loc)

    def parse_if_statement(self):
        """ Parse an if statement """
        loc = self.consume('if').loc
        self.consume('(')
        condition = self.parse_expression()
        self.consume(')')
        yes = self.parse_statement()
        if self.has_consumed('else'):
            no = self.parse_statement()
        else:
            no = nodes.Empty(None)
        return nodes.If(condition, yes, no, loc)

    def parse_switch_statement(self):
        """ Parse an switch statement """
        self.consume('switch')
        self.consume('(')
        condition = self.parse_expression()
        self.consume(')')
        # self.consume('{')
        # self.consume('case')
        # self.not_impl()
        # self.consume('default')
        # self.consume('}')
        # TODO: can we simply parse a compound here??
        body = self.parse_statement()
        return nodes.Switch(condition, body)

    def parse_case_statement(self):
        """ Parse a case """
        self.consume('case')
        self.parse_expression()
        self.consume(':')

    def parse_break_statement(self):
        """ Parse a break """
        loc = self.consume('break').loc
        self.consume(';')
        return nodes.Break(loc)

    def parse_while_statement(self):
        """ Parse a while statement """
        loc = self.consume('while').loc
        self.consume('(')
        condition = self.parse_expression()
        self.consume(')')
        body = self.parse_statement()
        return nodes.While(condition, body, loc)

    def parse_do_statement(self):
        """ Parse a do-while statement """
        loc = self.consume('do').loc
        body = self.parse_statement()
        self.consume('while')
        self.consume('(')
        condition = self.parse_expression()
        self.consume(')')
        self.parse_statement()
        return nodes.DoWhile(body, condition, loc)

    def parse_for_statement(self):
        """ Parse a for statement """
        loc = self.consume('for').loc
        self.consume('(')
        initial = self.parse_expression()
        self.consume(';')
        condition = self.parse_expression()
        self.consume(';')
        post = self.parse_expression()
        self.consume(')')
        body = self.parse_statement()
        return nodes.For(initial, condition, post, body, loc)

    def parse_return_statement(self):
        """ Parse a return statement """
        loc = self.consume('return').loc
        value = self.parse_expression()
        self.consume(';')
        return nodes.Return(value, loc)

    # Expression parts:
    def parse_expression(self):
        """ Parse an expression """
        return self.parse_binop_with_precedence(0)

    def parse_cast_expression(self):
        pass

    def parse_binop_with_precedence(self, prio):
        lhs = self.parse_primary_expression()
        LEFT_ASSOCIATIVE = 1
        RIGHT_ASSOCIATIVE = 2
        prio_map = {
            '=': (RIGHT_ASSOCIATIVE, 0),
            '+=': (RIGHT_ASSOCIATIVE, 0),
            '-=': (RIGHT_ASSOCIATIVE, 0),
            '*=': (RIGHT_ASSOCIATIVE, 0),
            '/=': (RIGHT_ASSOCIATIVE, 0),
            '>>=': (RIGHT_ASSOCIATIVE, 0),
            '<<=': (RIGHT_ASSOCIATIVE, 0),
            '++': (LEFT_ASSOCIATIVE, 50),
            '--': (LEFT_ASSOCIATIVE, 50),
            '+': (LEFT_ASSOCIATIVE, 50),
            '-': (LEFT_ASSOCIATIVE, 50),
            '*': (LEFT_ASSOCIATIVE, 80),
            '/': (LEFT_ASSOCIATIVE, 80),
            '%': (LEFT_ASSOCIATIVE, 80),
            '&': (LEFT_ASSOCIATIVE, 80),
            '|': (LEFT_ASSOCIATIVE, 80),
            '^': (LEFT_ASSOCIATIVE, 80),
            '<': (LEFT_ASSOCIATIVE, 80),
            '<=': (LEFT_ASSOCIATIVE, 80),
            '>': (LEFT_ASSOCIATIVE, 80),
            '>=': (LEFT_ASSOCIATIVE, 80),
            '!=': (LEFT_ASSOCIATIVE, 80),
            '==': (LEFT_ASSOCIATIVE, 80),
            '&&': (LEFT_ASSOCIATIVE, 80),
            '||': (LEFT_ASSOCIATIVE, 80),
            '>>': (LEFT_ASSOCIATIVE, 100),
            '<<': (LEFT_ASSOCIATIVE, 100),
        }

        # print('prio=', prio, self.peak)
        while self.peak in prio_map and prio_map[self.peak][1] >= prio:
            op = self.consume()
            op_prio, op_associativity = prio_map[op.val]
            rhs = self.parse_binop_with_precedence(op_prio)
            lhs = nodes.Binop(lhs, op.val, rhs, op.loc)
            # print(lhs)
        return lhs

    def parse_primary_expression(self):
        """ Parse a primary expression """
        if self.peak == 'ID':
            identifier = self.consume('ID')
            if self.peak == '(':
                # Function call!
                self.consume('(')
                args = []
                while self.peak != ')':
                    args.append(self.parse_expression())
                    if self.peak != ')':
                        self.consume(',')
                self.consume(')')
                expr = nodes.FunctionCall(identifier.val, args, identifier.loc)
            else:
                expr = nodes.VariableAccess(identifier.val, identifier.loc)
        elif self.peak == 'NUMBER':
            n = self.consume()
            expr = nodes.Constant(n.val, n.loc)
        elif self.peak == '(':
            self.consume('(')
            expr = self.parse_expression()
            self.consume(')')
        else:
            self.not_impl()
            raise NotImplementedError(str(self.peak))

        # Postfix operations:
        while self.peak in ['++']:
            op = self.consume('++')
            expr = nodes.Unop(op.val, expr, op.loc)
        return expr
